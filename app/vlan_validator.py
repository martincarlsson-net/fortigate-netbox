import logging
from typing import Dict, List

from .models import Switch

logger = logging.getLogger(__name__)


def _extract_netbox_vlan_info(interfaces: List[dict]) -> Dict[str, Dict[str, object]]:
    """
    Convert NetBox interface JSON into a simple mapping.

    Returns:
        {
          "port_name": {
            "native_vlan": "quarantine" or None,
            "allowed_vlans": ["quarantine", "vlan50", ...]
          },
          ...
        }

    VLANs are compared by name (interface.untagged_vlan.name, tagged_vlans[].name)
    to align with FortiGate's use of VLAN object names.
    """
    mapping: Dict[str, Dict[str, object]] = {}
    for iface in interfaces:
        name = iface.get("name")
        if not name:
            continue

        untagged = iface.get("untagged_vlan")
        tagged = iface.get("tagged_vlans") or []

        native_name = None
        if isinstance(untagged, dict):
            native_name = untagged.get("name") or untagged.get("display")

        allowed_names: List[str] = []
        for vlan in tagged:
            if not isinstance(vlan, dict):
                continue
            vlan_name = vlan.get("name") or vlan.get("display")
            if vlan_name:
                allowed_names.append(vlan_name)

        if not allowed_names and native_name:
            # Access port: allow only native VLAN
            allowed_names = [native_name]

        mapping[name] = {
            "native_vlan": native_name,
            "allowed_vlans": sorted(allowed_names),
        }
    return mapping


def validate_switch_vlans(switch: Switch, netbox_interfaces: List[dict]) -> None:
    """
    Compare FortiGate switch VLAN configuration with NetBox for a single switch.

    Logs:
      - INFO for matching ports
      - WARNING for missing ports
      - ERROR for mismatches or ambiguous configurations
    """
    nb_map = _extract_netbox_vlan_info(netbox_interfaces)

    for port_name, fg_port in switch.ports.items():
        nb_port = nb_map.get(port_name)
        if not nb_port:
            logger.warning(
                "Port %s on switch %s not found in NetBox.",
                port_name,
                switch.name,
            )
            continue

        nb_native = nb_port["native_vlan"]
        nb_allowed = nb_port["allowed_vlans"]

        fg_native = fg_port.native_vlan
        fg_allowed_sorted = sorted(fg_port.allowed_vlans)

        if "*" in fg_allowed_sorted:
            logger.warning(
                "Port %s on switch %s has 'allowed-vlans-all' enabled on "
                "FortiGate; skipping precise VLAN comparison.",
                port_name,
                switch.name,
            )
            continue

        if fg_native != nb_native or fg_allowed_sorted != nb_allowed:
            logger.error(
                "VLAN mismatch for %s/%s: FG native=%s allowed=%s, "
                "NB native=%s allowed=%s",
                switch.name,
                port_name,
                fg_native,
                fg_allowed_sorted,
                nb_native,
                nb_allowed,
            )
        else:
            logger.info(
                "VLANs match for %s/%s (native=%s, allowed=%s)",
                switch.name,
                port_name,
                fg_native,
                fg_allowed_sorted,
            )

