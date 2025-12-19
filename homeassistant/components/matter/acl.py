"""Access Control List (ACL) operations for Matter devices."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .const import (
    ACL_AUTH_MODE_CASE,
    ACL_PRIVILEGE_ADMINISTER,
    ACL_PRIVILEGE_OPERATE,
    ACL_VERIFY_INTERVAL,
    ACL_VERIFY_TIMEOUT,
    CLUSTER_ACCESS_CONTROL,
    CLUSTER_PRIVILEGE_MAP,
)
from .helpers import get_matter
from .models import ACLProvisioningResult, MatterACLEntry, MatterACLTarget

if TYPE_CHECKING:
    from matter_server.client import MatterClient

_LOGGER = logging.getLogger(__name__)


async def async_get_acl(hass: HomeAssistant, node_id: int) -> list[MatterACLEntry]:
    """Get ACL entries for a device.

    ACL is always on endpoint 0, cluster 0x001F, attribute 0.

    Args:
        hass: Home Assistant instance
        node_id: Matter node ID

    Returns:
        List of MatterACLEntry objects
    """
    matter = get_matter(hass)
    client = matter.matter_client

    acl_entries: list[MatterACLEntry] = []

    # Try cache first
    cached_acl = _get_acl_from_node_cache(client, node_id)
    if cached_acl is not None:
        _LOGGER.debug(
            "Found %d ACL entries from cache for node %s", len(cached_acl), node_id
        )
        return cached_acl

    # Fall back to reading via read_attribute API
    try:
        attribute_path = f"0/{CLUSTER_ACCESS_CONTROL}/0"  # ACL is always endpoint 0
        result = await client.read_attribute(
            node_id=node_id,
            attribute_path=attribute_path,
        )

        if result and isinstance(result, list):
            for entry in result:
                acl_entry = _parse_acl_entry(entry)
                if acl_entry:
                    acl_entries.append(acl_entry)

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error reading ACL for node %s: %s", node_id, err)

    return acl_entries


def _get_acl_from_node_cache(
    client: MatterClient, node_id: int
) -> list[MatterACLEntry] | None:
    """Try to get ACL from the node's cached endpoint 0 data."""
    try:
        for node in client.get_nodes():
            if node.node_id != node_id:
                continue

            endpoints = getattr(node, "endpoints", None)
            if not endpoints:
                return None

            endpoint = endpoints.get(0)  # ACL is always on endpoint 0
            if not endpoint:
                return None

            acl_value = None

            # Try get_cluster()
            if hasattr(endpoint, "get_cluster"):
                acl_cluster = endpoint.get_cluster(CLUSTER_ACCESS_CONTROL)
                if acl_cluster and hasattr(acl_cluster, "acl"):
                    acl_value = acl_cluster.acl

            if acl_value is None:
                return None

            # Parse ACL entries
            entries: list[MatterACLEntry] = []
            if isinstance(acl_value, list):
                for entry in acl_value:
                    parsed = _parse_acl_entry(entry)
                    if parsed:
                        entries.append(parsed)
            return entries

    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Error getting ACL from cache: %s", err)

    return None


def _parse_acl_entry(entry: Any) -> MatterACLEntry | None:
    """Parse an ACL entry from various formats."""

    def _get_value(obj: Any, *keys: Any, default: Any = None) -> Any:
        """Get value from dict or object attributes."""
        if isinstance(obj, dict):
            for k in keys:
                if k in obj and obj[k] is not None:
                    return obj[k]
        else:
            for k in keys:
                if isinstance(k, str) and hasattr(obj, k):
                    val = getattr(obj, k, None)
                    if val is not None:
                        return val
        return default

    def _safe_int(val: Any) -> int | None:
        """Convert value to int, handling Nullable types."""
        if val is None:
            return None
        if hasattr(val, "Null") or type(val).__name__ in ("Nullable", "NullValue"):
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    try:
        privilege = _get_value(entry, "1", 1, "privilege", "Privilege", default=0)
        auth_mode = _get_value(entry, "2", 2, "authMode", "AuthMode", default=0)
        subjects = _get_value(entry, "3", 3, "subjects", "Subjects", default=[])
        raw_targets = _get_value(entry, "4", 4, "targets", "Targets", default=[])
        fabric_index = _get_value(
            entry, "254", 254, "fabricIndex", "FabricIndex", default=0
        )

        # Parse targets
        targets: list[MatterACLTarget] = []
        if raw_targets and isinstance(raw_targets, list):
            targets = [
                MatterACLTarget(
                    cluster=_safe_int(
                        _get_value(t, "0", 0, "cluster", "Cluster", default=None)
                    ),
                    endpoint=_safe_int(
                        _get_value(t, "1", 1, "endpoint", "Endpoint", default=None)
                    ),
                    device_type=_safe_int(
                        _get_value(t, "2", 2, "deviceType", "DeviceType", default=None)
                    ),
                )
                for t in raw_targets
            ]

        # Convert subjects to native Python ints
        subjects_list: list[int | None] = []
        if isinstance(subjects, list):
            subjects_list = [int(s) if s is not None else None for s in subjects]

        return MatterACLEntry(
            privilege=int(privilege) if privilege is not None else 0,
            auth_mode=int(auth_mode) if auth_mode is not None else 0,
            subjects=[s for s in subjects_list if s is not None],
            targets=targets,
            fabric_index=int(fabric_index) if fabric_index is not None else 0,
        )

    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Error parsing ACL entry: %s", err)
        return None


def _get_cluster_privilege(cluster_id: int) -> int:
    """Get the required privilege level for a cluster."""
    return CLUSTER_PRIVILEGE_MAP.get(cluster_id, ACL_PRIVILEGE_OPERATE)


def _build_acl_entry_for_binding(
    source_node_id: int,
    target_endpoint_id: int,
    cluster_id: int,
) -> dict[str, Any]:
    """Build an ACL entry dict for a binding."""
    privilege = _get_cluster_privilege(cluster_id)

    return {
        "privilege": privilege,
        "authMode": ACL_AUTH_MODE_CASE,
        "subjects": [source_node_id],
        "targets": [
            {
                "cluster": cluster_id,
                "endpoint": target_endpoint_id,
                "deviceType": None,
            }
        ],
        "fabricIndex": 0,
    }


def _acl_entry_exists(
    existing_entries: list[MatterACLEntry],
    source_node_id: int,
    target_endpoint_id: int | None,
    cluster_id: int | None,
) -> bool:
    """Check if an ACL entry already grants the required access."""
    required_privilege = (
        _get_cluster_privilege(cluster_id) if cluster_id else ACL_PRIVILEGE_OPERATE
    )

    for entry in existing_entries:
        if entry.privilege < required_privilege:
            continue
        if entry.auth_mode != ACL_AUTH_MODE_CASE:
            continue
        if entry.subjects and source_node_id not in entry.subjects:
            continue

        if not entry.targets:
            return True

        for target in entry.targets:
            endpoint_match = (
                target.endpoint is None or target.endpoint == target_endpoint_id
            )
            cluster_match = target.cluster is None or target.cluster == cluster_id

            if endpoint_match and cluster_match:
                return True

    return False


def _acl_entry_to_dict(entry: MatterACLEntry) -> dict[str, Any]:
    """Convert an MatterACLEntry to dict format for writing."""
    targets = None
    if entry.targets:
        targets = [
            {
                "cluster": t.cluster,
                "endpoint": t.endpoint,
                "deviceType": t.device_type,
            }
            for t in entry.targets
        ]

    return {
        "privilege": entry.privilege,
        "authMode": entry.auth_mode,
        "subjects": entry.subjects if entry.subjects else None,
        "targets": targets,
        "fabricIndex": 0,
    }


async def async_write_acl(
    hass: HomeAssistant,
    node_id: int,
    acl_entries: list[dict[str, Any]],
) -> ACLProvisioningResult:
    """Write the complete ACL list to a device.

    IMPORTANT: The admin entry must be FIRST to prevent lockout.
    """
    # Safety check: ensure we have at least one admin entry
    has_admin = any(
        entry.get("privilege") == ACL_PRIVILEGE_ADMINISTER for entry in acl_entries
    )
    if not has_admin:
        _LOGGER.error(
            "SAFETY BLOCK - Refusing to write ACL without admin entry to node %s",
            node_id,
        )
        return ACLProvisioningResult(
            success=False,
            message="Safety block: Cannot write ACL without admin entry",
            error_type="invalid_request",
        )

    # Ensure admin entry is first
    if acl_entries and acl_entries[0].get("privilege") != ACL_PRIVILEGE_ADMINISTER:
        _LOGGER.warning("Admin entry is not first, reordering to prevent lockout")
        admin_entries = [
            e for e in acl_entries if e.get("privilege") == ACL_PRIVILEGE_ADMINISTER
        ]
        other_entries = [
            e for e in acl_entries if e.get("privilege") != ACL_PRIVILEGE_ADMINISTER
        ]
        acl_entries = admin_entries + other_entries

    matter = get_matter(hass)
    client = matter.matter_client

    try:
        _LOGGER.info("Writing %d ACL entries to node %s", len(acl_entries), node_id)

        # Use the dedicated set_acl_entry API
        result = await client.send_command(
            "set_acl_entry",
            node_id=node_id,
            entry=acl_entries,
        )

        # Check for errors
        if result is not None and isinstance(result, list):
            failed_entries = []
            for i, write_result in enumerate(result):
                status = None
                if isinstance(write_result, dict):
                    status = write_result.get("Status") or write_result.get("status")
                elif hasattr(write_result, "Status"):
                    status = write_result.Status

                if status is not None and status != 0:
                    failed_entries.append((i, status))
                    _LOGGER.error("ACL entry %d failed with status %s", i, status)

            if failed_entries:
                return ACLProvisioningResult(
                    success=False,
                    message=f"ACL write partially failed: {len(failed_entries)} entries rejected",
                    acl_entries_count=len(acl_entries) - len(failed_entries),
                    error_type="device_rejected",
                )

        return ACLProvisioningResult(
            success=True,
            message=f"Successfully wrote {len(acl_entries)} ACL entries",
            acl_entries_count=len(acl_entries),
        )

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error writing ACL to node %s: %s", node_id, err)
        return ACLProvisioningResult(
            success=False,
            message=f"Failed to write ACL: {err}",
            error_type="unknown_error",
        )


async def async_add_acl_entry(
    hass: HomeAssistant,
    node_id: int,
    source_node_id: int,
    target_endpoint_id: int,
    cluster_id: int,
) -> ACLProvisioningResult:
    """Add an ACL entry to allow a source node to access a target endpoint/cluster."""
    try:
        # Get current ACL entries
        current_entries = await async_get_acl(hass, node_id)

        # Check if entry already exists
        if _acl_entry_exists(
            current_entries, source_node_id, target_endpoint_id, cluster_id
        ):
            _LOGGER.info(
                "ACL entry already exists for node %s -> node %s ep %s cluster 0x%04X",
                source_node_id,
                node_id,
                target_endpoint_id,
                cluster_id,
            )
            return ACLProvisioningResult(
                success=True,
                message="ACL entry already exists",
                acl_entries_count=len(current_entries),
            )

        # Separate admin entries (must come first)
        admin_entries = [
            e for e in current_entries if e.privilege == ACL_PRIVILEGE_ADMINISTER
        ]
        other_entries = [
            e for e in current_entries if e.privilege != ACL_PRIVILEGE_ADMINISTER
        ]

        # Build the new ACL entry
        new_entry = _build_acl_entry_for_binding(
            source_node_id=source_node_id,
            target_endpoint_id=target_endpoint_id,
            cluster_id=cluster_id,
        )

        # Convert existing entries to dict format
        acl_list: list[dict[str, Any]] = [
            _acl_entry_to_dict(entry) for entry in admin_entries
        ]
        acl_list.extend(_acl_entry_to_dict(entry) for entry in other_entries)
        acl_list.append(new_entry)

        _LOGGER.info(
            "Adding ACL entry for node %s -> node %s ep %s cluster 0x%04X",
            source_node_id,
            node_id,
            target_endpoint_id,
            cluster_id,
        )

        # Write the updated ACL
        write_result = await async_write_acl(hass, node_id, acl_list)

        if not write_result.success:
            return write_result

        # Verify with polling
        return await _verify_acl_entry(
            hass, node_id, source_node_id, target_endpoint_id, cluster_id
        )

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error adding ACL entry: %s", err)
        return ACLProvisioningResult(
            success=False,
            message=f"Failed to add ACL entry: {err}",
            error_type="unknown_error",
        )


async def _verify_acl_entry(
    hass: HomeAssistant,
    node_id: int,
    source_node_id: int,
    target_endpoint_id: int,
    cluster_id: int,
) -> ACLProvisioningResult:
    """Verify that an ACL entry was successfully written."""
    max_attempts = int(ACL_VERIFY_TIMEOUT // ACL_VERIFY_INTERVAL)

    for attempt in range(max_attempts):
        verified_entries = await async_get_acl(hass, node_id)

        if _acl_entry_exists(
            verified_entries, source_node_id, target_endpoint_id, cluster_id
        ):
            _LOGGER.info(
                "Verified ACL entry on node %s after %d attempt(s)",
                node_id,
                attempt + 1,
            )
            return ACLProvisioningResult(
                success=True,
                message=f"Successfully added ACL entry ({len(verified_entries)} total)",
                acl_entries_count=len(verified_entries),
            )

        if attempt < max_attempts - 1:
            await asyncio.sleep(ACL_VERIFY_INTERVAL)

    _LOGGER.error(
        "ACL verification failed after %ds for node %s",
        ACL_VERIFY_TIMEOUT,
        node_id,
    )
    return ACLProvisioningResult(
        success=False,
        message=f"ACL write appeared to succeed but entry not found after {ACL_VERIFY_TIMEOUT}s",
        error_type="device_rejected",
    )


async def async_provision_acl_for_binding(
    hass: HomeAssistant,
    source_node_id: int,
    target_node_id: int,
    target_endpoint_id: int,
    cluster_id: int,
) -> ACLProvisioningResult:
    """Provision an ACL entry on the target device for a binding.

    This is the main entry point for ACL provisioning when creating bindings.
    """
    _LOGGER.info(
        "Provisioning ACL: node %s -> node %s ep %s cluster 0x%04X",
        source_node_id,
        target_node_id,
        target_endpoint_id,
        cluster_id,
    )

    return await async_add_acl_entry(
        hass=hass,
        node_id=target_node_id,
        source_node_id=source_node_id,
        target_endpoint_id=target_endpoint_id,
        cluster_id=cluster_id,
    )


async def async_remove_acl_entry(
    hass: HomeAssistant,
    node_id: int,
    entry_index: int,
) -> ACLProvisioningResult:
    """Remove a specific ACL entry by index.

    SAFETY: Will not remove admin entries to prevent lockout.
    """
    try:
        current_entries = await async_get_acl(hass, node_id)

        if entry_index < 0 or entry_index >= len(current_entries):
            return ACLProvisioningResult(
                success=False,
                message=f"Invalid entry index: {entry_index}",
                error_type="invalid_request",
            )

        entry_to_remove = current_entries[entry_index]

        # Safety check: don't remove admin entries
        if entry_to_remove.privilege == ACL_PRIVILEGE_ADMINISTER:
            _LOGGER.error("SAFETY BLOCK - Refusing to remove admin ACL entry")
            return ACLProvisioningResult(
                success=False,
                message="Safety block: Cannot remove admin ACL entry",
                error_type="invalid_request",
            )

        # Build new ACL list without the entry
        acl_list: list[dict[str, Any]] = []
        for i, entry in enumerate(current_entries):
            if i != entry_index:
                acl_list.append(_acl_entry_to_dict(entry))

        _LOGGER.info("Removing ACL entry %d from node %s", entry_index, node_id)

        return await async_write_acl(hass, node_id, acl_list)

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error removing ACL entry: %s", err)
        return ACLProvisioningResult(
            success=False,
            message=f"Failed to remove ACL entry: {err}",
            error_type="unknown_error",
        )
