"""Handle websocket api for Matter."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, Concatenate

from matter_server.client.models.node import MatterNode
from matter_server.common.errors import MatterError
from matter_server.common.helpers.util import dataclass_to_dict
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import ActiveConnection
from homeassistant.core import HomeAssistant, callback

from .acl import async_get_acl, async_provision_acl_for_binding, async_remove_acl_entry
from .adapter import MatterAdapter
from .binding import async_create_binding, async_delete_binding, async_get_bindings
from .helpers import MissingNode, get_matter, node_from_ha_device_id

ID = "id"
TYPE = "type"
DEVICE_ID = "device_id"


ERROR_NODE_NOT_FOUND = "node_not_found"


@callback
def async_register_api(hass: HomeAssistant) -> None:
    """Register all of our api endpoints."""
    websocket_api.async_register_command(hass, websocket_commission)
    websocket_api.async_register_command(hass, websocket_commission_on_network)
    websocket_api.async_register_command(hass, websocket_set_thread_dataset)
    websocket_api.async_register_command(hass, websocket_set_wifi_credentials)
    websocket_api.async_register_command(hass, websocket_node_diagnostics)
    websocket_api.async_register_command(hass, websocket_ping_node)
    websocket_api.async_register_command(hass, websocket_open_commissioning_window)
    websocket_api.async_register_command(hass, websocket_remove_matter_fabric)
    websocket_api.async_register_command(hass, websocket_interview_node)
    # Binding and ACL commands
    websocket_api.async_register_command(hass, websocket_get_bindings)
    websocket_api.async_register_command(hass, websocket_create_binding)
    websocket_api.async_register_command(hass, websocket_delete_binding)
    websocket_api.async_register_command(hass, websocket_get_acl)
    websocket_api.async_register_command(hass, websocket_provision_acl)
    websocket_api.async_register_command(hass, websocket_remove_acl)


def async_get_node(
    func: Callable[
        [HomeAssistant, ActiveConnection, dict[str, Any], MatterAdapter, MatterNode],
        Coroutine[Any, Any, None],
    ],
) -> Callable[
    [HomeAssistant, ActiveConnection, dict[str, Any], MatterAdapter],
    Coroutine[Any, Any, None],
]:
    """Decorate async function to get node."""

    @wraps(func)
    async def async_get_node_func(
        hass: HomeAssistant,
        connection: ActiveConnection,
        msg: dict[str, Any],
        matter: MatterAdapter,
    ) -> None:
        """Provide user specific data and store to function."""
        node = node_from_ha_device_id(hass, msg[DEVICE_ID])
        if not node:
            raise MissingNode(
                f"Could not resolve Matter node from device id {msg[DEVICE_ID]}"
            )
        await func(hass, connection, msg, matter, node)

    return async_get_node_func


def async_get_matter_adapter(
    func: Callable[
        [HomeAssistant, ActiveConnection, dict[str, Any], MatterAdapter],
        Coroutine[Any, Any, None],
    ],
) -> Callable[
    [HomeAssistant, ActiveConnection, dict[str, Any]], Coroutine[Any, Any, None]
]:
    """Decorate function to get the MatterAdapter."""

    @wraps(func)
    async def _get_matter(
        hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
    ) -> None:
        """Provide the Matter client to the function."""
        matter = get_matter(hass)

        await func(hass, connection, msg, matter)

    return _get_matter


def async_handle_failed_command[**_P](
    func: Callable[
        Concatenate[HomeAssistant, ActiveConnection, dict[str, Any], _P],
        Coroutine[Any, Any, None],
    ],
) -> Callable[
    Concatenate[HomeAssistant, ActiveConnection, dict[str, Any], _P],
    Coroutine[Any, Any, None],
]:
    """Decorate function to handle MatterError and send relevant error."""

    @wraps(func)
    async def async_handle_failed_command_func(
        hass: HomeAssistant,
        connection: ActiveConnection,
        msg: dict[str, Any],
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> None:
        """Handle MatterError within function and send relevant error."""
        try:
            await func(hass, connection, msg, *args, **kwargs)
        except MatterError as err:
            connection.send_error(msg[ID], str(err.error_code), err.args[0])
        except MissingNode as err:
            connection.send_error(msg[ID], ERROR_NODE_NOT_FOUND, err.args[0])

    return async_handle_failed_command_func


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/commission",
        vol.Required("code"): str,
        vol.Optional("network_only"): bool,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
async def websocket_commission(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
) -> None:
    """Add a device to the network and commission the device."""
    await matter.matter_client.commission_with_code(
        msg["code"], network_only=msg.get("network_only", True)
    )
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/commission_on_network",
        vol.Required("pin"): int,
        vol.Optional("ip_addr"): str,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
async def websocket_commission_on_network(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
) -> None:
    """Commission a device already on the network."""
    await matter.matter_client.commission_on_network(
        msg["pin"], ip_addr=msg.get("ip_addr")
    )
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/set_thread",
        vol.Required("thread_operation_dataset"): str,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
async def websocket_set_thread_dataset(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
) -> None:
    """Set thread dataset."""
    await matter.matter_client.set_thread_operational_dataset(
        msg["thread_operation_dataset"]
    )
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/set_wifi_credentials",
        vol.Required("network_name"): str,
        vol.Required("password"): str,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
async def websocket_set_wifi_credentials(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
) -> None:
    """Set WiFi credentials for a device."""
    await matter.matter_client.set_wifi_credentials(
        ssid=msg["network_name"], credentials=msg["password"]
    )
    connection.send_result(msg[ID])


@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/node_diagnostics",
        vol.Required(DEVICE_ID): str,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
@async_get_node
async def websocket_node_diagnostics(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
    node: MatterNode,
) -> None:
    """Gather diagnostics for the given node."""
    result = await matter.matter_client.node_diagnostics(node_id=node.node_id)
    connection.send_result(msg[ID], dataclass_to_dict(result))


@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/ping_node",
        vol.Required(DEVICE_ID): str,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
@async_get_node
async def websocket_ping_node(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
    node: MatterNode,
) -> None:
    """Ping node on the currently known IP-adress(es)."""
    result = await matter.matter_client.ping_node(node_id=node.node_id)
    connection.send_result(msg[ID], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/open_commissioning_window",
        vol.Required(DEVICE_ID): str,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
@async_get_node
async def websocket_open_commissioning_window(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
    node: MatterNode,
) -> None:
    """Open a commissioning window to commission a device present on this controller to another."""
    result = await matter.matter_client.open_commissioning_window(node_id=node.node_id)
    connection.send_result(msg[ID], dataclass_to_dict(result))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/remove_matter_fabric",
        vol.Required(DEVICE_ID): str,
        vol.Required("fabric_index"): int,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
@async_get_node
async def websocket_remove_matter_fabric(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
    node: MatterNode,
) -> None:
    """Remove Matter fabric from a device."""
    await matter.matter_client.remove_matter_fabric(
        node_id=node.node_id, fabric_index=msg["fabric_index"]
    )
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/interview_node",
        vol.Required(DEVICE_ID): str,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
@async_get_node
async def websocket_interview_node(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
    node: MatterNode,
) -> None:
    """Interview a node."""
    await matter.matter_client.interview_node(node_id=node.node_id)
    connection.send_result(msg[ID])


# --- Binding and ACL WebSocket Commands ---


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/get_bindings",
        vol.Required(DEVICE_ID): str,
        vol.Required("endpoint_id"): vol.Coerce(int),
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
@async_get_node
async def websocket_get_bindings(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
    node: MatterNode,
) -> None:
    """Get bindings for a device endpoint."""
    bindings = await async_get_bindings(hass, node.node_id, msg["endpoint_id"])
    connection.send_result(msg[ID], [b.to_dict() for b in bindings])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/create_binding",
        vol.Required(DEVICE_ID): str,
        vol.Required("endpoint_id"): vol.Coerce(int),
        vol.Required("cluster_id"): vol.Coerce(int),
        vol.Required("target_device_id"): str,
        vol.Required("target_endpoint_id"): vol.Coerce(int),
        vol.Optional("verify", default=True): bool,
        vol.Optional("provision_acl", default=True): bool,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
@async_get_node
async def websocket_create_binding(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
    node: MatterNode,
) -> None:
    """Create a binding from source device to target device."""
    # Resolve target device_id to node
    target_node = node_from_ha_device_id(hass, msg["target_device_id"])
    if not target_node:
        raise MissingNode(
            f"Could not resolve target Matter node from device id {msg['target_device_id']}"
        )

    result = await async_create_binding(
        hass=hass,
        source_node_id=node.node_id,
        source_endpoint_id=msg["endpoint_id"],
        cluster_id=msg["cluster_id"],
        target_node_id=target_node.node_id,
        target_endpoint_id=msg["target_endpoint_id"],
        verify=msg.get("verify", True),
        provision_acl=msg.get("provision_acl", True),
    )
    connection.send_result(msg[ID], result.to_dict())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/delete_binding",
        vol.Required(DEVICE_ID): str,
        vol.Required("endpoint_id"): vol.Coerce(int),
        vol.Required("cluster_id"): vol.Coerce(int),
        vol.Required("target_device_id"): str,
        vol.Required("target_endpoint_id"): vol.Coerce(int),
        vol.Optional("verify", default=True): bool,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
@async_get_node
async def websocket_delete_binding(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
    node: MatterNode,
) -> None:
    """Delete a binding from source device."""
    # Resolve target device_id to node
    target_node = node_from_ha_device_id(hass, msg["target_device_id"])
    if not target_node:
        raise MissingNode(
            f"Could not resolve target Matter node from device id {msg['target_device_id']}"
        )

    result = await async_delete_binding(
        hass=hass,
        source_node_id=node.node_id,
        source_endpoint_id=msg["endpoint_id"],
        cluster_id=msg["cluster_id"],
        target_node_id=target_node.node_id,
        target_endpoint_id=msg["target_endpoint_id"],
        verify=msg.get("verify", True),
    )
    connection.send_result(msg[ID], result.to_dict())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/get_acl",
        vol.Required(DEVICE_ID): str,
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
@async_get_node
async def websocket_get_acl(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
    node: MatterNode,
) -> None:
    """Get ACL entries for a device."""
    acl_entries = await async_get_acl(hass, node.node_id)
    connection.send_result(msg[ID], [e.to_dict() for e in acl_entries])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/provision_acl",
        vol.Required(DEVICE_ID): str,
        vol.Required("source_device_id"): str,
        vol.Required("endpoint_id"): vol.Coerce(int),
        vol.Required("cluster_id"): vol.Coerce(int),
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
@async_get_node
async def websocket_provision_acl(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
    node: MatterNode,
) -> None:
    """Provision an ACL entry on target device for source device."""
    # Resolve source device_id to node
    source_node = node_from_ha_device_id(hass, msg["source_device_id"])
    if not source_node:
        raise MissingNode(
            f"Could not resolve source Matter node from device id {msg['source_device_id']}"
        )

    result = await async_provision_acl_for_binding(
        hass=hass,
        source_node_id=source_node.node_id,
        target_node_id=node.node_id,
        target_endpoint_id=msg["endpoint_id"],
        cluster_id=msg["cluster_id"],
    )
    connection.send_result(msg[ID], result.to_dict())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "matter/remove_acl",
        vol.Required(DEVICE_ID): str,
        vol.Required("entry_index"): vol.Coerce(int),
    }
)
@websocket_api.async_response
@async_handle_failed_command
@async_get_matter_adapter
@async_get_node
async def websocket_remove_acl(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    matter: MatterAdapter,
    node: MatterNode,
) -> None:
    """Remove an ACL entry from a device."""
    result = await async_remove_acl_entry(
        hass=hass,
        node_id=node.node_id,
        entry_index=msg["entry_index"],
    )
    connection.send_result(msg[ID], result.to_dict())
