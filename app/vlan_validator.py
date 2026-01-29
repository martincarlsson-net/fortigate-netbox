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


def _extract_netbox_mode(iface: dict) -> Optional[str]:
    """Extract NetBox interface mode value."""
    mode = iface.get("mode")
    if isinstance(mode, dict):
        mode = mode.get("value")
    if isinstance(mode, str) and mode:
        return mode.strip().lower()
    return None


def _extract_netbox_vlan_info(interfaces: List[dict]) -> Dict[str, Dict[str, object]]:
    """Convert NetBox interface JSON into a normalized mapping.

    Returns:
        {
          "port_name_lower": {
            "name": "Port1",
            "native_vlan": "VLAN-31" or None,
            "tagged_vlans": ["VLAN-50", ...] or ["*"] for tagged-all,
            "mode": "access" | "tagged" | "tagged-all" | "unknown"
          },
          ...
        }

    Notes:
      - Port names are matched case-insensitively.
      - VLAN names are normalized so FortiGate-style "vlan31" matches NetBox-style "VLAN-31".
      - mode=access: tagged_vlans=[]
      - mode=tagged: tagged_vlans=explicit list from tagged_vlans field
      - mode=tagged-all: tagged_vlans=["*"]
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
        mode = _extract_netbox_mode(iface)

        native_name: Optional[str] = None
        if isinstance(untagged, dict):
            native_name = _normalize_vlan_name(untagged.get("name") or untagged.get("display"))

        tagged_set = set()
        for v in tagged:
            if not isinstance(v, dict):
                continue
            vn = _normalize_vlan_name(v.get("name") or v.get("display"))
            if vn:
                tagged_set.add(vn)

        # NetBox semantics by mode:
        # - access: only untagged_vlan, tagged_vlans ignored/empty
        # - tagged: untagged_vlan (native) + tagged_vlans (explicit tagged VLANs)
        # - tagged-all: untagged_vlan (native), tagged_vlans empty => treat as "*" (all tagged)
        if mode == "tagged-all":
            tagged_list = ["*"]
        elif mode == "access":
            tagged_list = []
        else:
            # tagged (or unknown): use explicit tagged_vlans list
            tagged_list = sorted(tagged_set)

        mapping[key] = {
            "name": raw_name,
            "native_vlan": native_name,
            "tagged_vlans": tagged_list,
            "mode": mode or "unknown",
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
        nb_tagged = nb_port["tagged_vlans"]
        nb_mode = nb_port.get("mode")

        fg_tagged_raw = list(fg_port.allowed_vlans)  # now treated as tagged VLANs
        fg_native = _normalize_vlan_name(fg_port.native_vlan)
        fg_tagged = sorted({v for v in (_normalize_vlan_name(v) for v in fg_tagged_raw) if v})

        # Tagged-all handling: if either side says "*" treat it as tagged-all and only compare native VLAN
        fg_is_all = "*" in fg_tagged_raw
        nb_is_all = isinstance(nb_tagged, list) and "*" in nb_tagged
        if fg_is_all or nb_is_all:
            if fg_native != nb_native:
                logger.error(
                    "VLAN mismatch for %s/%s (NetBox iface=%s, mode=%s): FG native=%s tagged=ALL, NB native=%s tagged=ALL",
                    switch.name,
                    port_name,
                    nb_port.get("name"),
                    nb_mode,
                    fg_native,
                    nb_native,
                )
            else:
                logger.info(
                    "VLANs match for %s/%s (NetBox iface=%s, mode=%s, native=%s, tagged=ALL)",
                    switch.name,
                    port_name,
                    nb_port.get("name"),
                    nb_mode,
                    fg_native,
                )
            continue

        if fg_native != nb_native or fg_tagged != nb_tagged:
            logger.error(
                "VLAN mismatch for %s/%s (NetBox iface=%s, mode=%s): FG native=%s tagged=%s, "
                "NB native=%s tagged=%s",
                switch.name,
                port_name,
                nb_port.get("name"),
                nb_mode,
                fg_native,
                fg_tagged,
                nb_native,
                nb_tagged,
            )
        else:
            logger.info(
                "VLANs match for %s/%s (NetBox iface=%s, mode=%s, native=%s, tagged=%s)",
                switch.name,
                port_name,
                nb_port.get("name"),
                nb_mode,
                fg_native,
                fg_tagged,
            )
