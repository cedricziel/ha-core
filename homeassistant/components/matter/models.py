"""Models used for the Matter integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from chip.clusters import Objects as clusters
from chip.clusters.Objects import Cluster, ClusterAttributeDescriptor
from matter_server.client.models.device_types import DeviceType
from matter_server.client.models.node import MatterEndpoint

from homeassistant.const import Platform

from .entity import MatterEntityDescription

type SensorValueTypes = type[
    clusters.uint | int | clusters.Nullable | clusters.float32 | float
]


# A sentinel object to detect if a parameter is supplied or not.
class _UNSET_TYPE:
    pass


UNSET = _UNSET_TYPE()


class MatterDeviceInfo(TypedDict):
    """Dictionary with Matter Device info.

    Used to send to other Matter controllers,
    such as Google Home to prevent duplicated devices.

    Reference: https://developers.home.google.com/matter/device-deduplication
    """

    unique_id: str
    vendor_id: str  # vendorId hex string
    product_id: str  # productId hex string


@dataclass
class MatterEntityInfo:
    """Info discovered from (primary) Matter Attribute to create entity."""

    # MatterEndpoint to which the value(s) belongs
    endpoint: MatterEndpoint

    # the home assistant platform for which an entity should be created
    platform: Platform

    # All attributes that need to be watched by entity (incl. primary)
    attributes_to_watch: list[type[ClusterAttributeDescriptor]]

    # the entity description to use
    entity_description: MatterEntityDescription

    # entity class to use to instantiate the entity
    entity_class: type

    # the original discovery schema used to create this entity
    discovery_schema: MatterDiscoverySchema

    @property
    def primary_attribute(self) -> type[ClusterAttributeDescriptor]:
        """Return Primary Attribute belonging to the entity."""
        return self.attributes_to_watch[0]


@dataclass
class MatterDiscoverySchema:
    """Matter discovery schema.

    The Matter endpoint and its (primary) Attribute
    for an entity must match these conditions.
    """

    # specify the hass platform for which this scheme applies (e.g. light, sensor)
    platform: Platform

    # platform-specific entity description
    entity_description: MatterEntityDescription

    # entity class to use to instantiate the entity
    entity_class: type

    # DISCOVERY OPTIONS

    # [required] attributes that ALL need to be present
    # on the node for this scheme to pass (minimal one == primary)
    required_attributes: tuple[type[ClusterAttributeDescriptor], ...]

    # [optional] the value's endpoint must contain this devicetype(s)
    device_type: tuple[type[DeviceType] | DeviceType, ...] | None = None

    # [optional] the value's endpoint must NOT contain this devicetype(s)
    not_device_type: tuple[type[DeviceType] | DeviceType, ...] | None = None

    # [optional] the endpoint's vendor_id must match ANY of these values
    vendor_id: tuple[int, ...] | None = None

    # [optional] the endpoint's product_id must match ANY of these values
    product_id: tuple[int, ...] | None = None

    # [optional] the endpoint's product_name must match ANY of these values
    product_name: tuple[str, ...] | None = None

    # [optional] the attribute's endpoint_id must match ANY of these values
    endpoint_id: tuple[int, ...] | None = None

    # [optional] attributes that MAY NOT be present
    # (on the same endpoint) for this scheme to pass
    absent_attributes: tuple[type[ClusterAttributeDescriptor], ...] | None = None

    # [optional] cluster(s) that MAY NOT be present
    # (on ANY endpoint) for this scheme to pass
    absent_clusters: tuple[type[Cluster], ...] | None = None

    # [optional] additional attributes that may be present (on the same endpoint)
    # these attributes are copied over to attributes_to_watch and
    # are not discovered by other entities
    optional_attributes: tuple[type[ClusterAttributeDescriptor], ...] | None = None

    # [optional] the primary attribute's cluster featuremap must contain this value
    # for example for the DoorSensor on a DoorLock Cluster
    featuremap_contains: int | None = None

    # [optional] bool to specify if this primary value may be discovered
    # by multiple platforms
    allow_multi: bool = False

    # [optional] the primary attribute value may not be null/None
    allow_none_value: bool = False

    # [optional] the primary attribute value must contain this value
    # for example for the AcceptedCommandList
    # NOTE: only works for list values
    value_contains: Any = UNSET

    # [optional] the secondary (required) attribute value must contain this value
    # for example for the AcceptedCommandList
    # NOTE: only works for list values
    secondary_value_contains: Any = UNSET

    # [optional] the primary attribute value must NOT have this value
    # for example to filter out invalid values (such as empty string instead of null)
    # in case of a list value, the list may not contain this value
    value_is_not: Any = UNSET

    # [optional] the secondary (required) attribute value must NOT have this value
    # for example to filter out empty lists in list sensor values
    secondary_value_is_not: Any = UNSET


# --- Binding and ACL Models ---


@dataclass
class MatterBindingEntry:
    """Represents a Matter binding entry.

    Bindings are device-to-device communication links stored in the
    Binding cluster (0x001E) on the source device.
    """

    source_node_id: int
    source_endpoint_id: int
    cluster_id: int
    target_node_id: int | None = None
    target_endpoint_id: int | None = None
    target_group_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "source_node_id": self.source_node_id,
            "source_endpoint_id": self.source_endpoint_id,
            "cluster_id": self.cluster_id,
            "target_node_id": self.target_node_id,
            "target_endpoint_id": self.target_endpoint_id,
            "target_group_id": self.target_group_id,
        }


@dataclass
class MatterACLTarget:
    """Represents an ACL target restriction.

    Targets restrict which endpoints/clusters an ACL entry applies to.
    """

    cluster: int | None = None
    endpoint: int | None = None
    device_type: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "cluster": self.cluster,
            "endpoint": self.endpoint,
            "device_type": self.device_type,
        }


@dataclass
class MatterACLEntry:
    """Represents a Matter Access Control List entry.

    ACL entries are stored in the AccessControl cluster (0x001F) on endpoint 0
    and control which nodes can communicate with the device.
    """

    privilege: int  # 1=View, 2=ProxyView, 3=Operate, 4=Manage, 5=Administer
    auth_mode: int  # 1=PASE, 2=CASE, 3=Group  # codespell:ignore pase
    subjects: list[int]  # Node IDs or Group IDs (empty = all matching authMode)
    targets: list[MatterACLTarget]  # Restrictions (empty = all endpoints/clusters)
    fabric_index: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        privilege_names = {
            1: "View",
            2: "ProxyView",
            3: "Operate",
            4: "Manage",
            5: "Administer",
        }
        auth_mode_names = {1: "PASE", 2: "CASE", 3: "Group"}  # codespell:ignore pase
        return {
            "privilege": self.privilege,
            "privilege_name": privilege_names.get(
                self.privilege, f"Unknown ({self.privilege})"
            ),
            "auth_mode": self.auth_mode,
            "auth_mode_name": auth_mode_names.get(
                self.auth_mode, f"Unknown ({self.auth_mode})"
            ),
            "subjects": self.subjects,
            "targets": [t.to_dict() for t in self.targets],
            "fabric_index": self.fabric_index,
        }


@dataclass
class BindingOperationResult:
    """Result of a binding operation."""

    success: bool
    verified: bool  # True if binding was confirmed on device
    message: str
    bindings_count: int = 0
    error_type: str = "success"  # success, permission_denied, device_unavailable, etc.

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "success": self.success,
            "verified": self.verified,
            "message": self.message,
            "bindings_count": self.bindings_count,
            "error_type": self.error_type,
        }


@dataclass
class ACLProvisioningResult:
    """Result of an ACL provisioning operation."""

    success: bool
    message: str
    acl_entries_count: int = 0
    error_type: str = "success"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "success": self.success,
            "message": self.message,
            "acl_entries_count": self.acl_entries_count,
            "error_type": self.error_type,
        }
