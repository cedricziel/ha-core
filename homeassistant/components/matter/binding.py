"""Binding operations for Matter devices.

Ported from matter_binding_helper custom integration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .const import BINDING_VERIFY_INTERVAL, BINDING_VERIFY_TIMEOUT, CLUSTER_BINDING
from .helpers import get_matter
from .models import BindingOperationResult, MatterBindingEntry

if TYPE_CHECKING:
    from matter_server.client import MatterClient

_LOGGER = logging.getLogger(__name__)


async def async_get_bindings(
    hass: HomeAssistant, node_id: int, endpoint_id: int
) -> list[MatterBindingEntry]:
    """Get bindings for a specific node endpoint.

    Args:
        hass: Home Assistant instance
        node_id: Matter node ID
        endpoint_id: Endpoint ID to read bindings from

    Returns:
        List of MatterBindingEntry objects
    """
    matter = get_matter(hass)
    client = matter.matter_client

    bindings: list[MatterBindingEntry] = []

    # First try to get from cached node data
    cached_bindings = _get_bindings_from_node_cache(client, node_id, endpoint_id)
    if cached_bindings is not None:
        _LOGGER.debug(
            "Found %d bindings from cache for node %s ep %s",
            len(cached_bindings),
            node_id,
            endpoint_id,
        )
        return cached_bindings

    # Fall back to reading via read_attribute API
    try:
        attribute_path = f"{endpoint_id}/{CLUSTER_BINDING}/0"
        _LOGGER.debug("Reading bindings from attribute path: %s", attribute_path)

        result = await client.read_attribute(
            node_id=node_id,
            attribute_path=attribute_path,
        )

        if result and isinstance(result, list):
            bindings = _parse_binding_value(node_id, endpoint_id, result)

    except Exception as err:  # noqa: BLE001
        _LOGGER.error(
            "Error reading bindings for node %s endpoint %s: %s",
            node_id,
            endpoint_id,
            err,
        )

    return bindings


def _get_bindings_from_node_cache(
    client: MatterClient, node_id: int, endpoint_id: int
) -> list[MatterBindingEntry] | None:
    """Try to get bindings from the node's cached endpoint data.

    Returns None if bindings are not found in the cache.
    Returns empty list if the binding attribute exists but is empty.
    """
    try:
        for node in client.get_nodes():
            if node.node_id != node_id:
                continue

            endpoints = getattr(node, "endpoints", None)
            if not endpoints:
                return None

            endpoint = endpoints.get(endpoint_id)
            if not endpoint:
                return None

            binding_value = None

            # Try get_cluster() to get the Binding cluster
            if hasattr(endpoint, "get_cluster"):
                binding_cluster = endpoint.get_cluster(CLUSTER_BINDING)
                if binding_cluster:
                    if hasattr(binding_cluster, "binding"):
                        binding_value = binding_cluster.binding
                    elif hasattr(binding_cluster, "get_attribute_value"):
                        binding_value = binding_cluster.get_attribute_value(0)

            # Try accessing clusters dict directly
            if binding_value is None and hasattr(endpoint, "clusters"):
                clusters = endpoint.clusters
                if isinstance(clusters, dict):
                    binding_cluster = clusters.get(CLUSTER_BINDING)
                    if binding_cluster and hasattr(binding_cluster, "binding"):
                        binding_value = binding_cluster.binding

            if binding_value is None:
                return None

            return _parse_binding_value(node_id, endpoint_id, binding_value)

    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Error getting bindings from cache: %s", err)

    return None


def _parse_binding_value(
    node_id: int, endpoint_id: int, binding_value: Any
) -> list[MatterBindingEntry]:
    """Parse a binding attribute value into MatterBindingEntry objects."""
    bindings: list[MatterBindingEntry] = []

    if not binding_value or not isinstance(binding_value, list):
        return bindings

    for binding in binding_value:
        cluster_id = 0
        target_node = None
        target_endpoint = None
        target_group = None

        if isinstance(binding, dict):
            # Dict format - try multiple key naming conventions
            cluster_id = (
                binding.get("Cluster")
                or binding.get("cluster")
                or binding.get("ClusterId")
                or 0
            )
            target_node = binding.get("Node") or binding.get("node")
            target_endpoint = binding.get("Endpoint") or binding.get("endpoint")
            target_group = binding.get("Group") or binding.get("group")
        elif hasattr(binding, "cluster"):
            # Object format (from Matter SDK)
            cluster_id = getattr(binding, "cluster", 0) or 0
            target_node = getattr(binding, "node", None)
            target_endpoint = getattr(binding, "endpoint", None)
            target_group = getattr(binding, "group", None)

        bindings.append(
            MatterBindingEntry(
                source_node_id=node_id,
                source_endpoint_id=endpoint_id,
                cluster_id=cluster_id,
                target_node_id=target_node,
                target_endpoint_id=target_endpoint,
                target_group_id=target_group,
            )
        )

    return bindings


async def async_create_binding(
    hass: HomeAssistant,
    source_node_id: int,
    source_endpoint_id: int,
    cluster_id: int,
    target_node_id: int | None = None,
    target_endpoint_id: int | None = None,
    target_group_id: int | None = None,
    verify: bool = True,
    provision_acl: bool = True,
) -> BindingOperationResult:
    """Create a new binding with optional verification and ACL provisioning.

    Args:
        hass: Home Assistant instance
        source_node_id: Source Matter node ID
        source_endpoint_id: Source endpoint ID
        cluster_id: Cluster ID for the binding
        target_node_id: Target node ID (for unicast binding)
        target_endpoint_id: Target endpoint ID (for unicast binding)
        target_group_id: Target group ID (for group binding)
        verify: If True, verify the binding was created by reading back
        provision_acl: If True, provision ACL on target device (unicast only)

    Returns:
        BindingOperationResult with success/verification status
    """
    # Import here to avoid circular imports
    from .acl import async_provision_acl_for_binding  # noqa: PLC0415

    matter = get_matter(hass)
    client = matter.matter_client

    # Check if source node is available
    if not _is_node_available(client, source_node_id):
        return BindingOperationResult(
            success=False,
            verified=False,
            message="Source device is not available",
            error_type="device_unavailable",
        )

    try:
        _LOGGER.info(
            "Creating binding from node %s ep %s to node %s ep %s (cluster %s)",
            source_node_id,
            source_endpoint_id,
            target_node_id,
            target_endpoint_id,
            cluster_id,
        )

        # Get current bindings
        current_bindings = await async_get_bindings(
            hass, source_node_id, source_endpoint_id
        )

        # Build new binding entry
        new_binding: dict[str, Any] = {
            "cluster": cluster_id,
            "fabricIndex": 0,  # Will be set by the device
        }
        if target_node_id is not None:
            new_binding["node"] = target_node_id
        if target_endpoint_id is not None:
            new_binding["endpoint"] = target_endpoint_id
        if target_group_id is not None:
            new_binding["group"] = target_group_id

        # Build the full binding list
        binding_list = []
        for b in current_bindings:
            entry: dict[str, Any] = {
                "cluster": b.cluster_id,
                "fabricIndex": 0,
            }
            if b.target_node_id is not None:
                entry["node"] = b.target_node_id
            if b.target_endpoint_id is not None:
                entry["endpoint"] = b.target_endpoint_id
            if b.target_group_id is not None:
                entry["group"] = b.target_group_id
            binding_list.append(entry)

        binding_list.append(new_binding)

        # Write the binding attribute
        attribute_path = f"{source_endpoint_id}/{CLUSTER_BINDING}/0"
        await client.write_attribute(
            node_id=source_node_id,
            attribute_path=attribute_path,
            value=binding_list,
        )

        # Provision ACL on target device if requested
        if (
            provision_acl
            and target_node_id is not None
            and target_endpoint_id is not None
        ):
            _LOGGER.info(
                "Provisioning ACL on target node %s for source node %s",
                target_node_id,
                source_node_id,
            )
            acl_result = await async_provision_acl_for_binding(
                hass=hass,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                target_endpoint_id=target_endpoint_id,
                cluster_id=cluster_id,
            )

            if not acl_result.success:
                _LOGGER.warning(
                    "ACL provisioning failed: %s (binding was still created)",
                    acl_result.message,
                )

        # Verify the binding was created if requested
        if verify:
            await asyncio.sleep(BINDING_VERIFY_INTERVAL)
            return await _verify_binding_created(
                hass,
                source_node_id,
                source_endpoint_id,
                target_node_id,
                target_endpoint_id,
                target_group_id,
                cluster_id,
            )

        return BindingOperationResult(
            success=True,
            verified=False,
            message="Binding created (verification skipped)",
            bindings_count=len(binding_list),
        )

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error creating binding: %s", err)
        return BindingOperationResult(
            success=False,
            verified=False,
            message=f"Failed to create binding: {err}",
            error_type="unknown_error",
        )


async def async_delete_binding(
    hass: HomeAssistant,
    source_node_id: int,
    source_endpoint_id: int,
    cluster_id: int,
    target_node_id: int | None = None,
    target_endpoint_id: int | None = None,
    target_group_id: int | None = None,
    verify: bool = True,
) -> BindingOperationResult:
    """Delete a binding from a device.

    Args:
        hass: Home Assistant instance
        source_node_id: Source Matter node ID
        source_endpoint_id: Source endpoint ID
        cluster_id: Cluster ID for the binding to delete
        target_node_id: Target node ID
        target_endpoint_id: Target endpoint ID
        target_group_id: Target group ID
        verify: If True, verify the binding was deleted

    Returns:
        BindingOperationResult with success status
    """
    matter = get_matter(hass)
    client = matter.matter_client

    if not _is_node_available(client, source_node_id):
        return BindingOperationResult(
            success=False,
            verified=False,
            message="Source device is not available",
            error_type="device_unavailable",
        )

    try:
        _LOGGER.info(
            "Deleting binding from node %s ep %s to node %s ep %s (cluster %s)",
            source_node_id,
            source_endpoint_id,
            target_node_id,
            target_endpoint_id,
            cluster_id,
        )

        # Get current bindings
        current_bindings = await async_get_bindings(
            hass, source_node_id, source_endpoint_id
        )

        # Build new binding list without the target binding
        binding_list = []
        removed = False
        for b in current_bindings:
            if _binding_matches(
                b, target_node_id, target_endpoint_id, target_group_id, cluster_id
            ):
                removed = True
                continue  # Skip this binding

            entry: dict[str, Any] = {
                "cluster": b.cluster_id,
                "fabricIndex": 0,
            }
            if b.target_node_id is not None:
                entry["node"] = b.target_node_id
            if b.target_endpoint_id is not None:
                entry["endpoint"] = b.target_endpoint_id
            if b.target_group_id is not None:
                entry["group"] = b.target_group_id
            binding_list.append(entry)

        if not removed:
            return BindingOperationResult(
                success=False,
                verified=False,
                message="Binding not found",
                error_type="invalid_request",
            )

        # Write the updated binding attribute
        attribute_path = f"{source_endpoint_id}/{CLUSTER_BINDING}/0"
        await client.write_attribute(
            node_id=source_node_id,
            attribute_path=attribute_path,
            value=binding_list,
        )

        # Verify deletion if requested
        if verify:
            await asyncio.sleep(BINDING_VERIFY_INTERVAL)
            read_bindings = await async_get_bindings(
                hass, source_node_id, source_endpoint_id
            )
            still_exists = any(
                _binding_matches(
                    b, target_node_id, target_endpoint_id, target_group_id, cluster_id
                )
                for b in read_bindings
            )

            if still_exists:
                return BindingOperationResult(
                    success=True,
                    verified=False,
                    message="Binding delete written but still found on device",
                    bindings_count=len(read_bindings),
                    error_type="device_rejected",
                )

            return BindingOperationResult(
                success=True,
                verified=True,
                message="Binding deleted and verified",
                bindings_count=len(read_bindings),
            )

        return BindingOperationResult(
            success=True,
            verified=False,
            message="Binding deleted (verification skipped)",
            bindings_count=len(binding_list),
        )

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error deleting binding: %s", err)
        return BindingOperationResult(
            success=False,
            verified=False,
            message=f"Failed to delete binding: {err}",
            error_type="unknown_error",
        )


async def _verify_binding_created(
    hass: HomeAssistant,
    source_node_id: int,
    source_endpoint_id: int,
    target_node_id: int | None,
    target_endpoint_id: int | None,
    target_group_id: int | None,
    cluster_id: int,
) -> BindingOperationResult:
    """Verify that a binding was successfully created on the device."""
    start_time = asyncio.get_event_loop().time()

    while (asyncio.get_event_loop().time() - start_time) < BINDING_VERIFY_TIMEOUT:
        read_bindings = await async_get_bindings(
            hass, source_node_id, source_endpoint_id
        )

        binding_found = any(
            _binding_matches(
                b, target_node_id, target_endpoint_id, target_group_id, cluster_id
            )
            for b in read_bindings
        )

        if binding_found:
            return BindingOperationResult(
                success=True,
                verified=True,
                message="Binding created and verified on device",
                bindings_count=len(read_bindings),
            )

        await asyncio.sleep(BINDING_VERIFY_INTERVAL)

    return BindingOperationResult(
        success=True,
        verified=False,
        message="Binding written but not verified within timeout",
        error_type="device_rejected",
    )


def _binding_matches(
    binding: MatterBindingEntry,
    target_node_id: int | None,
    target_endpoint_id: int | None,
    target_group_id: int | None,
    cluster_id: int,
) -> bool:
    """Check if a binding matches the given criteria."""
    if binding.cluster_id != cluster_id:
        return False
    if target_node_id is not None and binding.target_node_id != target_node_id:
        return False
    if (
        target_endpoint_id is not None
        and binding.target_endpoint_id != target_endpoint_id
    ):
        return False
    if target_group_id is not None and binding.target_group_id != target_group_id:
        return False
    return True


def _is_node_available(client: MatterClient, node_id: int) -> bool:
    """Check if a Matter node is available."""
    for node in client.get_nodes():
        if node.node_id == node_id:
            return getattr(node, "available", True)
    return False
