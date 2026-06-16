"""Map Matter groups onto Home Assistant group entities."""

from typing import TYPE_CHECKING

from matter_server.client.models import device_types
from matter_server.common.errors import NodeNotExists

from homeassistant.const import Platform

from .group import MatterGroup, MatterGroupEntity
from .light import MatterGroupLight
from .switch import MatterGroupSwitch

if TYPE_CHECKING:
    from matter_server.client import MatterClient

# Device types whose endpoints map onto each group platform. Scoped to light
# and switch for now; other platforms can be added as group support matures.
LIGHT_DEVICE_TYPES: tuple[type[device_types.DeviceType], ...] = (
    device_types.ColorTemperatureLight,
    device_types.DimmableLight,
    device_types.DimmablePlugInUnit,
    device_types.ExtendedColorLight,
    device_types.MountedDimmableLoadControl,
    device_types.OnOffLight,
)
SWITCH_DEVICE_TYPES: tuple[type[device_types.DeviceType], ...] = (
    device_types.OnOffPlugInUnit,
    device_types.MountedOnOffLoadControl,
)

GROUP_ENTITY_CLASSES: dict[Platform, type[MatterGroupEntity]] = {
    Platform.LIGHT: MatterGroupLight,
    Platform.SWITCH: MatterGroupSwitch,
}


def _resolve_platform(
    matter_client: MatterClient, group: MatterGroup
) -> Platform | None:
    """Determine the HA platform for a group from its members' device types."""
    for node_id, endpoint_id in group.members:
        try:
            node = matter_client.get_node(node_id)
        except KeyError, NodeNotExists:
            continue
        if (endpoint := node.endpoints.get(endpoint_id)) is None:
            continue
        if any(
            device_type in endpoint.device_types for device_type in LIGHT_DEVICE_TYPES
        ):
            return Platform.LIGHT
        if any(
            device_type in endpoint.device_types for device_type in SWITCH_DEVICE_TYPES
        ):
            return Platform.SWITCH
    return None


def async_discover_group(
    matter_client: MatterClient, group: MatterGroup
) -> tuple[Platform, MatterGroupEntity] | None:
    """Build the group entity for a group, or None if no platform matches."""
    platform = _resolve_platform(matter_client, group)
    if platform is None:
        return None
    entity_class = GROUP_ENTITY_CLASSES[platform]
    return platform, entity_class(matter_client, group)
