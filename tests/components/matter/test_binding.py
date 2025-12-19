"""Test the binding and ACL module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.components.matter.api import DEVICE_ID, ID, TYPE
from homeassistant.components.matter.models import (
    MatterACLEntry,
    MatterACLTarget,
    MatterBindingEntry,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .common import setup_integration_with_node_fixture

from tests.typing import WebSocketGenerator


@pytest.fixture
async def matter_node(hass: HomeAssistant, matter_client: MagicMock) -> MagicMock:
    """Set up a Matter node for testing."""
    return await setup_integration_with_node_fixture(hass, "onoff_light", matter_client)


async def test_get_bindings(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    matter_client: MagicMock,
    matter_node: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test the get_bindings command."""
    ws_client = await hass_ws_client(hass)

    # Get the device ID from registry
    device = device_registry.async_get_device(
        identifiers={("matter", "deviceid_1234-0000000000000001-MatterNodeDevice")}
    )
    assert device is not None

    # Mock read_attribute to return empty binding list
    matter_client.read_attribute = AsyncMock(return_value=[])

    await ws_client.send_json(
        {
            ID: 1,
            TYPE: "matter/get_bindings",
            DEVICE_ID: device.id,
            "endpoint_id": 1,
        }
    )
    msg = await ws_client.receive_json()

    assert msg["success"]
    assert msg["result"] == []


async def test_create_binding(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    matter_client: MagicMock,
    matter_node: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test the create_binding command."""
    ws_client = await hass_ws_client(hass)

    # Get the device ID from registry
    device = device_registry.async_get_device(
        identifiers={("matter", "deviceid_1234-0000000000000001-MatterNodeDevice")}
    )
    assert device is not None

    # Mock the required methods
    matter_client.read_attribute = AsyncMock(return_value=[])
    matter_client.write_attribute = AsyncMock(return_value=None)
    matter_client.send_command = AsyncMock(return_value=None)

    await ws_client.send_json(
        {
            ID: 1,
            TYPE: "matter/create_binding",
            DEVICE_ID: device.id,
            "endpoint_id": 1,
            "cluster_id": 6,  # On/Off cluster
            "target_device_id": device.id,  # Binding to self for test
            "target_endpoint_id": 1,
            "verify": False,  # Skip verification for test
            "provision_acl": False,  # Skip ACL for test
        }
    )
    msg = await ws_client.receive_json()

    assert msg["success"]
    assert msg["result"]["success"] is True


async def test_delete_binding(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    matter_client: MagicMock,
    matter_node: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test the delete_binding command."""
    ws_client = await hass_ws_client(hass)

    # Get the device ID from registry
    device = device_registry.async_get_device(
        identifiers={("matter", "deviceid_1234-0000000000000001-MatterNodeDevice")}
    )
    assert device is not None

    # Mock read_attribute to return a binding that we'll delete
    matter_client.read_attribute = AsyncMock(
        return_value=[
            {
                "cluster": 6,
                "node": 1,
                "endpoint": 1,
                "fabricIndex": 1,
            }
        ]
    )
    matter_client.write_attribute = AsyncMock(return_value=None)

    await ws_client.send_json(
        {
            ID: 1,
            TYPE: "matter/delete_binding",
            DEVICE_ID: device.id,
            "endpoint_id": 1,
            "cluster_id": 6,
            "target_device_id": device.id,
            "target_endpoint_id": 1,
            "verify": False,
        }
    )
    msg = await ws_client.receive_json()

    assert msg["success"]
    assert msg["result"]["success"] is True


async def test_get_acl(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    matter_client: MagicMock,
    matter_node: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test the get_acl command."""
    ws_client = await hass_ws_client(hass)

    # Get the device ID from registry
    device = device_registry.async_get_device(
        identifiers={("matter", "deviceid_1234-0000000000000001-MatterNodeDevice")}
    )
    assert device is not None

    # Mock read_attribute to return ACL entries
    matter_client.read_attribute = AsyncMock(
        return_value=[
            {
                "1": 5,  # privilege: Administer
                "2": 2,  # authMode: CASE
                "3": [],  # subjects
                "4": None,  # targets
                "254": 1,  # fabricIndex
            }
        ]
    )

    await ws_client.send_json(
        {
            ID: 1,
            TYPE: "matter/get_acl",
            DEVICE_ID: device.id,
        }
    )
    msg = await ws_client.receive_json()

    assert msg["success"]
    assert len(msg["result"]) == 1
    assert msg["result"][0]["privilege"] == 5
    assert msg["result"][0]["privilege_name"] == "Administer"


async def test_provision_acl(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    matter_client: MagicMock,
    matter_node: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test the provision_acl command."""
    ws_client = await hass_ws_client(hass)

    # Get the device ID from registry
    device = device_registry.async_get_device(
        identifiers={("matter", "deviceid_1234-0000000000000001-MatterNodeDevice")}
    )
    assert device is not None

    # Mock read_attribute to return existing admin ACL
    matter_client.read_attribute = AsyncMock(
        return_value=[
            {
                "1": 5,  # privilege: Administer
                "2": 2,  # authMode: CASE
                "3": [],  # subjects
                "4": None,  # targets
                "254": 1,  # fabricIndex
            }
        ]
    )
    matter_client.send_command = AsyncMock(return_value=None)

    await ws_client.send_json(
        {
            ID: 1,
            TYPE: "matter/provision_acl",
            DEVICE_ID: device.id,
            "source_device_id": device.id,
            "endpoint_id": 1,
            "cluster_id": 6,
        }
    )
    msg = await ws_client.receive_json()

    assert msg["success"]


async def test_remove_acl_safety_block(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    matter_client: MagicMock,
    matter_node: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test that remove_acl blocks removal of admin entry."""
    ws_client = await hass_ws_client(hass)

    # Get the device ID from registry
    device = device_registry.async_get_device(
        identifiers={("matter", "deviceid_1234-0000000000000001-MatterNodeDevice")}
    )
    assert device is not None

    # Mock read_attribute to return only admin ACL
    matter_client.read_attribute = AsyncMock(
        return_value=[
            {
                "1": 5,  # privilege: Administer
                "2": 2,  # authMode: CASE
                "3": [],  # subjects
                "4": None,  # targets
                "254": 1,  # fabricIndex
            }
        ]
    )

    await ws_client.send_json(
        {
            ID: 1,
            TYPE: "matter/remove_acl",
            DEVICE_ID: device.id,
            "entry_index": 0,  # Try to remove admin entry
        }
    )
    msg = await ws_client.receive_json()

    assert msg["success"]
    # Result should indicate failure due to safety block
    assert msg["result"]["success"] is False
    assert "admin" in msg["result"]["message"].lower()


def test_binding_entry_to_dict() -> None:
    """Test MatterBindingEntry.to_dict method."""
    entry = MatterBindingEntry(
        source_node_id=1,
        source_endpoint_id=1,
        cluster_id=6,
        target_node_id=2,
        target_endpoint_id=1,
        target_group_id=None,
    )
    result = entry.to_dict()

    assert result["source_node_id"] == 1
    assert result["cluster_id"] == 6
    assert result["target_node_id"] == 2
    assert result["target_group_id"] is None


def test_acl_entry_to_dict() -> None:
    """Test MatterACLEntry.to_dict method."""
    entry = MatterACLEntry(
        privilege=3,
        auth_mode=2,
        subjects=[1, 2],
        targets=[MatterACLTarget(cluster=6, endpoint=1, device_type=None)],
        fabric_index=1,
    )
    result = entry.to_dict()

    assert result["privilege"] == 3
    assert result["privilege_name"] == "Operate"
    assert result["auth_mode"] == 2
    assert result["auth_mode_name"] == "CASE"
    assert len(result["subjects"]) == 2
    assert len(result["targets"]) == 1
