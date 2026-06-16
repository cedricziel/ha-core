"""Matter group support.

Matter groups (group messaging / "groupcast") let a controller actuate many
endpoints with a single IPv6 multicast message instead of one unicast command
per device. This module maps a server-owned Matter group onto a single Home
Assistant entity that:

* sends commands to the group via multicast (write path), and
* aggregates the real state of all members via per-member attribute
  subscriptions (read path).

Because group messaging is write-only at the protocol level, there is no group
state to read back. After a groupcast every member actuates and emits its own
``ATTRIBUTE_UPDATED`` event, so the aggregated state converges from the member
subscriptions and the entity is *not* assumed-state.

NOTE: This feature depends on group support in the Matter server / Python
client that is not yet released. The required client contract is:

* ``MatterClient.get_groups() -> list[MatterGroup]``
* ``MatterClient.send_group_command(group_id, command)`` (fire-and-forget)
* ``EventType.GROUP_ADDED`` / ``GROUP_REMOVED`` / ``GROUP_UPDATED``

The :class:`MatterGroup` model below mirrors the shape the client is expected
to expose; it is defined locally until the upstream model lands, at which point
this definition is replaced by an import.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from chip.clusters.Objects import ClusterAttributeDescriptor, ClusterCommand, NullValue
from matter_server.common.errors import MatterError, NodeNotExists
from matter_server.common.helpers.util import create_attribute_path
from matter_server.common.models import EventType, ServerInfoMessage

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity

if TYPE_CHECKING:
    from matter_server.client import MatterClient
    from matter_server.client.models.node import MatterEndpoint


@dataclass
class MatterGroup:
    """Represent a Matter group as reported by the Matter server.

    Mirrors the (planned) upstream client model. ``members`` holds the
    ``(node_id, endpoint_id)`` of every endpoint bound to the group.
    """

    group_id: int
    name: str
    members: list[tuple[int, int]] = field(default_factory=list)


def aggregate_is_on(values: list[bool | None]) -> bool:
    """Return True if any member reports an on state."""
    return any(bool(value) for value in values)


def aggregate_mean(values: list[int | None]) -> int | None:
    """Return the rounded mean of the present (non-None) values."""
    present = [value for value in values if value is not None]
    if not present:
        return None
    return round(sum(present) / len(present))


def first_present[_T](values: list[_T | None]) -> _T | None:
    """Return the first non-None value, if any."""
    return next((value for value in values if value is not None), None)


class MatterGroupEntity(Entity):
    """Base entity for a Matter group.

    Subclasses declare ``_watched_attributes`` (the member attributes whose
    updates should re-aggregate group state) and implement
    ``_update_from_members`` to map those onto Home Assistant state.
    """

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_assumed_state = False

    # member attributes that should trigger a re-aggregation when they change
    _watched_attributes: tuple[type[ClusterAttributeDescriptor], ...] = ()

    def __init__(self, matter_client: MatterClient, group: MatterGroup) -> None:
        """Initialize the group entity."""
        self.matter_client = matter_client
        self._group = group
        self._lifecycle_unsubscribes: list[Callable[[], None]] = []
        self._member_unsubscribes: list[Callable[[], None]] = []
        server_info = cast(ServerInfoMessage, matter_client.server_info)
        self._attr_unique_id = (
            f"{server_info.compressed_fabric_id:016X}-group-{group.group_id}"
        )
        self._attr_name = group.name
        self._members = self._resolve_members()
        self._update_state()

    def _resolve_members(self) -> list[MatterEndpoint]:
        """Resolve group members to their MatterEndpoint objects."""
        members: list[MatterEndpoint] = []
        for node_id, endpoint_id in self._group.members:
            try:
                node = self.matter_client.get_node(node_id)
            except KeyError, NodeNotExists:
                continue
            if (endpoint := node.endpoints.get(endpoint_id)) is not None:
                members.append(endpoint)
        return members

    async def async_added_to_hass(self) -> None:
        """Subscribe to member updates and group lifecycle events."""
        await super().async_added_to_hass()
        self._subscribe_members()
        # group membership/lifecycle changes
        self._lifecycle_unsubscribes.append(
            self.matter_client.subscribe_events(
                callback=self._on_group_updated,
                event_filter=EventType.GROUP_UPDATED,
            )
        )
        self._lifecycle_unsubscribes.append(
            self.matter_client.subscribe_events(
                callback=self._on_group_removed,
                event_filter=EventType.GROUP_REMOVED,
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from all events."""
        for unsub in (*self._member_unsubscribes, *self._lifecycle_unsubscribes):
            unsub()
        self._member_unsubscribes.clear()
        self._lifecycle_unsubscribes.clear()

    def _subscribe_members(self) -> None:
        """Subscribe to the watched attributes of every member endpoint."""
        seen: set[tuple[int, str]] = set()
        for member in self._members:
            node_id = member.node.node_id
            for attribute in self._watched_attributes:
                attr_path = create_attribute_path(
                    member.endpoint_id, attribute.cluster_id, attribute.attribute_id
                )
                if (node_id, attr_path) in seen:
                    continue
                seen.add((node_id, attr_path))
                self._member_unsubscribes.append(
                    self.matter_client.subscribe_events(
                        callback=self._on_member_event,
                        event_filter=EventType.ATTRIBUTE_UPDATED,
                        node_filter=node_id,
                        attr_path_filter=attr_path,
                    )
                )
            # availability follows the member node
            self._member_unsubscribes.append(
                self.matter_client.subscribe_events(
                    callback=self._on_member_event,
                    event_filter=EventType.NODE_UPDATED,
                    node_filter=node_id,
                )
            )

    @callback
    def _on_member_event(self, event: EventType, data: Any = None) -> None:
        """Re-aggregate group state when a member changes."""
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _on_group_updated(self, event: EventType, data: Any = None) -> None:
        """Handle group membership changes by re-subscribing members."""
        if _group_id_from_event(data) != self._group.group_id:
            return
        if isinstance(data, MatterGroup):
            self._group = data
        for unsub in self._member_unsubscribes:
            unsub()
        self._member_unsubscribes.clear()
        self._members = self._resolve_members()
        self._subscribe_members()
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _on_group_removed(self, event: EventType, data: Any = None) -> None:
        """Remove the entity when its group is deleted on the server."""
        if _group_id_from_event(data) != self._group.group_id:
            return
        er.async_get(self.hass).async_remove(self.entity_id)

    @callback
    def _update_state(self) -> None:
        """Recompute availability and call subclass state aggregation."""
        self._attr_available = any(member.node.available for member in self._members)
        self._update_from_members()

    @callback
    def _update_from_members(self) -> None:
        """Aggregate member state into Home Assistant state (subclass hook)."""

    @callback
    def _member_values(self, attribute: type[ClusterAttributeDescriptor]) -> list[Any]:
        """Return the value of an attribute across all members (null as None)."""
        values: list[Any] = []
        for member in self._members:
            value = member.get_attribute_value(None, attribute)
            values.append(None if value == NullValue else value)
        return values

    async def send_group_command(self, command: ClusterCommand) -> None:
        """Send a command to the whole group via multicast."""
        try:
            await self.matter_client.send_group_command(
                group_id=self._group.group_id, command=command
            )
        except MatterError as err:
            raise HomeAssistantError(str(err) or err.__class__.__name__) from err


def _group_id_from_event(data: Any) -> int | None:
    """Extract a group id from a lifecycle event payload."""
    if isinstance(data, MatterGroup):
        return data.group_id
    if isinstance(data, int):
        return data
    if isinstance(data, dict):
        return data.get("group_id")
    return getattr(data, "group_id", None)
