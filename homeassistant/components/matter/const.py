"""Constants for the Matter integration."""

import logging

ADDON_SLUG = "core_matter_server"

CONF_INTEGRATION_CREATED_ADDON = "integration_created_addon"
CONF_USE_ADDON = "use_addon"

DOMAIN = "matter"
LOGGER = logging.getLogger(__package__)

# prefixes to identify device identifier id types
ID_TYPE_DEVICE_ID = "deviceid"
ID_TYPE_SERIAL = "serial"

FEATUREMAP_ATTRIBUTE_ID = 65532

# --- Binding and ACL Constants ---

# Cluster IDs
CLUSTER_BINDING = 0x001E  # 30
CLUSTER_ACCESS_CONTROL = 0x001F  # 31

# ACL Attribute IDs
ATTR_ACL = 0

# ACL Privilege levels (from Matter spec)
ACL_PRIVILEGE_VIEW = 1
ACL_PRIVILEGE_PROXY_VIEW = 2
ACL_PRIVILEGE_OPERATE = 3
ACL_PRIVILEGE_MANAGE = 4
ACL_PRIVILEGE_ADMINISTER = 5

# ACL Auth modes (from Matter spec)
ACL_AUTH_MODE_PASE = 1  # codespell:ignore pase
ACL_AUTH_MODE_CASE = 2
ACL_AUTH_MODE_GROUP = 3

# Verification timing (seconds)
BINDING_VERIFY_INTERVAL = 0.5
BINDING_VERIFY_TIMEOUT = 5.0
ACL_VERIFY_INTERVAL = 2.0
ACL_VERIFY_TIMEOUT = 10.0

# Cluster privilege mappings - which privilege level is needed for each cluster
# Default is OPERATE for control clusters, VIEW for read-only
CLUSTER_PRIVILEGE_MAP: dict[int, int] = {
    0x0006: ACL_PRIVILEGE_OPERATE,  # On/Off
    0x0008: ACL_PRIVILEGE_OPERATE,  # Level Control
    0x0201: ACL_PRIVILEGE_OPERATE,  # Thermostat
    0x0300: ACL_PRIVILEGE_OPERATE,  # Color Control
    0x0101: ACL_PRIVILEGE_OPERATE,  # Door Lock
    0x0102: ACL_PRIVILEGE_OPERATE,  # Window Covering
}
