import logging
import re
from typing import Dict, List, Optional

from .models import Switch

logger = logging.getLogger(__name__)


def _normalize_port_name(name: str) -> str:
    return name.strip().lower()


def _normalize_vlan_name(name: Optional[str]) -> Optional[str]:
    """Normalize VLAN names across NetBox and FortiGate.

    Examples:
      - "vlan31" -> "VLAN-31"
      - "VLAN-31" -> "VLAN-31"
      - "VLAN-31 (31)" -> "VLAN-31"
    """
    if not name:
        return None

    s = str(name).strip()

    m = re.match(r"^vlan[- ]?(\d+)$", s, flags=re.IGNORECASE)
    if m:
        return f"VLAN-{int(m.group(1))}"

    m = re.match(r"^vlan[- ]?(\d+)\s*\(\d+\)$", s, flags=re.IGNORECASE)
    if m:
        return f"VLAN-{int(m.group(1))}"

    return s


def _extract_netbox_vlan_info(interfaces: List[dict]) -> Dict[str, Dict[str, object]]:
    """Convert NetBox interface JSON into a normalized mapping.

    Returns:
        {
          "port_name_lower": {
            "name": "Port1",
            "native_vlan": "VLAN-31" or None,
            "allowed_vlans": ["VLAN-31", "VLAN-50", ...]
          },
          ...
        }

    Notes:
      - Port names are matched case-insensitively.
      - VLAN names are normalized so FortiGate-style "vlan31" matches NetBox-style "VLAN-31".
    """
    mapping: Dict[str, Dict[str, object]] = {}

    for iface in interfaces:
        raw_name = iface.get("name")
        if not raw_name:
            continue

        key = _normalize_port_name(raw_name)
        if key in mapping and mapping[key].get("name") != raw_name:
            logger.warning(
                "NetBox contains interfaces that differ only by case: %s and %s; using %s",
                mapping[key].get("name"),
                raw_name,
                mapping[key].get("name"),
            )
            continue

        untagged = iface.get("untagged_vlan")
        tagged = iface.get("tagged_vlans") or []

        native_name: Optional[str] = None
        if isinstance(untagged, dict):
            native_name = _normalize_vlan_name(untagged.get("name") or untagged.get("display"))

        allowed_set = set()
        for vlan in tagged:
            if not isinstance(vlan, dict):
                continue
            vlan_name = _normalize_vlan_name(vlan.get("name") or vlan.get("display"))
            if vlan_name:
                allowed_set.add(vlan_name)

        if not allowed_set and native_name:
            # Access port: allow only native VLAN
            allowed_set.add(native_name)

        mapping[key] = {
            "name": raw_name,
            "native_vlan": native_name,
            "allowed_vlans": sorted(allowed_set),
        }

    return mapping


def validate_switch_vlans(switch: Switch, netbox_interfaces: List[dict]) -> None:
    """Compare FortiGate switch VLAN configuration with NetBox for a single switch."""

    nb_map = _extract_netbox_vlan_info(netbox_interfaces)

    for port_name, fg_port in switch.ports.items():
        nb_port = nb_map.get(_normalize_port_name(port_name))
        if not nb_port:
            logger.warning(
                "Port %s on switch %s not found in NetBox (case-insensitive match).",
                port_name,
                switch.name,
            )
            continue

        nb_native = nb_port["native_vlan"]
        nb_allowed = nb_port["allowed_vlans"]

        fg_allowed = list(fg_port.allowed_vlans)
        if "*" in fg_allowed:
            logger.warning(
                "Port %s on switch %s has 'allowed-vlans-all' enabled on FortiGate; "
                "skipping precise VLAN comparison.",
                port_name,
                switch.name,
            )
            continue

        fg_native = _normalize_vlan_name(fg_port.native_vlan)

        fg_allowed_norm = sorted(
            {v for v in (_normalize_vlan_name(v) for v in fg_allowed) if v is not None}
        )

        if fg_native != nb_native or fg_allowed_norm != nb_allowed:
            logger.error(
                "VLAN mismatch for %s/%s (NetBox iface=%s): FG native=%s allowed=%s, "
                "NB native=%s allowed=%s",
                switch.name,
                port_name,
                nb_port.get("name"),
                fg_native,
                fg_allowed_norm,
                nb_native,
                nb_allowed,
            )
        else:
            logger.info(
                "VLANs match for %s/%s (NetBox iface=%s, native=%s, allowed=%s)",
                switch.name,
                port_name,
                nb_port.get("name"),
                fg_native,
                fg_allowed_norm,
            )
