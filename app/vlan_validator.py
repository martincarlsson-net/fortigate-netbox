import logging
import re
from typing import Dict, List, Optional, Tuple

from .models import Switch

logger = logging.getLogger(__name__)


def _normalize_port_name(name: str) -> str:
    return name.strip().lower()


def _port_sort_key(name: str) -> Tuple[str, int]:
    """
    Sort ports naturally: port1, port2, ..., port10 (instead of port1, port10, port2).
    """
    s = (name or "").strip().lower()
    m = re.match(r"^(.*?)(\d+)$", s)
    if m:
        return (m.group(1), int(m.group(2)))
    return (s, 0)


def _extract_vlan_vid(value: object) -> Optional[int]:
    """Extract vlan vid as integer from values like 'vlan31', 'VLAN-31', '31'."""
    if value is None:
        return None
    if isinstance(value, int):
        return value

    s = str(value).strip()
    if not s:
        return None

    m = re.match(r"^(?:vlan[- ]?)?(\d+)$", s, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))

    # NetBox sometimes provides 'display' like 'VLAN-31 (31)'
    m = re.match(r"^(?:vlan[- ]?)?(\d+)\s*\(\d+\)$", s, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))

    return None


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
            "id": 123,
            "name": "Port1",
            "native_vlan_vid": 31 or None,
            "tagged_vlan_vids": [50, ...] or ["*"] for tagged-all,
            "mode": "access" | "tagged" | "tagged-all" | "unknown"
          },
          ...
        }

    Notes:
      - Port names are matched case-insensitively.
      - VLANs are represented by vid integers (not names) to avoid dependency on naming.
      - mode=access: tagged_vlan_vids=[]
      - mode=tagged: tagged_vlan_vids=explicit list from tagged_vlans field
      - mode=tagged-all: tagged_vlan_vids=["*"]
    """
    mapping: Dict[str, Dict[str, object]] = {}

    for iface in interfaces:
        iface_id = iface.get("id")
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

        native_vid: Optional[int] = None
        if isinstance(untagged, dict):
            native_vid = untagged.get("vid")
            if not isinstance(native_vid, int):
                native_vid = _extract_vlan_vid(untagged.get("name") or untagged.get("display"))

        tagged_set: set[int] = set()
        for v in tagged:
            if not isinstance(v, dict):
                continue
            vv = v.get("vid")
            if not isinstance(vv, int):
                vv = _extract_vlan_vid(v.get("name") or v.get("display"))
            if isinstance(vv, int):
                tagged_set.add(vv)

        # NetBox semantics by mode:
        # - access: only untagged_vlan, tagged_vlans ignored/empty
        # - tagged: untagged_vlan (native) + tagged_vlans (explicit tagged VLANs)
        # - tagged-all: untagged_vlan (native), tagged_vlans empty => treat as "*" (all tagged)
        if mode == "tagged-all":
            tagged_list: List[object] = ["*"]
        elif mode == "access":
            tagged_list = []
        else:
            tagged_list = sorted(tagged_set)

        mapping[key] = {
            "id": iface_id,
            "name": raw_name,
            "native_vlan_vid": native_vid,
            "tagged_vlan_vids": tagged_list,
            "mode": mode or "unknown",
        }

    return mapping


def validate_switch_vlans(switch: Switch, netbox_interfaces: List[dict]) -> List[dict]:
    """Compare FortiGate switch VLAN configuration with NetBox for a single switch.

    Returns:
        List of mismatch dictionaries, each containing:
        - switch: switch name
        - port: port name
        - netbox_interface_id: NetBox interface ID
        - netbox_interface_name: NetBox interface name
        - desired_mode: 'access' or 'tagged'
        - desired_native_vid: vlan vid (int) or None
        - desired_tagged_vids: list of vlan vids (int)
    """

    nb_map = _extract_netbox_vlan_info(netbox_interfaces)
    mismatches: List[dict] = []

    for port_name in sorted(switch.ports.keys(), key=_port_sort_key):
        fg_port = switch.ports[port_name]
        nb_port = nb_map.get(_normalize_port_name(port_name))
        if not nb_port:
            logger.warning(
                "Port %s on switch %s not found in NetBox (case-insensitive match).",
                port_name,
                switch.name,
            )
            continue

        nb_native = nb_port["native_vlan_vid"]
        nb_tagged = nb_port["tagged_vlan_vids"]
        nb_mode = nb_port.get("mode")
        nb_iface_id = nb_port.get("id")

        fg_tagged_raw = list(fg_port.allowed_vlans)  # now treated as tagged VLANs
        fg_native = _extract_vlan_vid(fg_port.native_vlan)
        fg_tagged = sorted({v for v in (_extract_vlan_vid(v) for v in fg_tagged_raw) if isinstance(v, int)})

        # Tagged-all handling: if either side says "*" treat it as tagged-all and only compare native VLAN
        fg_is_all = "*" in fg_tagged_raw
        nb_is_all = isinstance(nb_tagged, list) and "*" in nb_tagged
        if fg_is_all or nb_is_all:
            if fg_native != nb_native:
                logger.error(
                    "VLAN mismatch for %s/%s (NetBox iface=%s, mode=%s): FG native_vid=%s tagged=ALL, NB native_vid=%s tagged=ALL",
                    switch.name,
                    port_name,
                    nb_port.get("name"),
                    nb_mode,
                    fg_native,
                    nb_native,
                )
                mismatches.append(
                    {
                        "switch": switch.name,
                        "port": port_name,
                        "netbox_interface_id": nb_iface_id,
                        "netbox_interface_name": nb_port.get("name"),
                        "desired_mode": "tagged",  # conservative default for now
                        "desired_native_vid": fg_native,
                        "desired_tagged_vids": [],  # tagged-all not handled yet
                    }
                )
            else:
                logger.info(
                    "VLANs match for %s/%s (NetBox iface=%s, mode=%s, native_vid=%s, tagged=ALL)",
                    switch.name,
                    port_name,
                    nb_port.get("name"),
                    nb_mode,
                    fg_native,
                )
            continue

        if fg_native != nb_native or fg_tagged != nb_tagged:
            logger.error(
                "VLAN mismatch for %s/%s (NetBox iface=%s, mode=%s): FG native_vid=%s tagged_vids=%s, "
                "NB native_vid=%s tagged_vids=%s",
                switch.name,
                port_name,
                nb_port.get("name"),
                nb_mode,
                fg_native,
                fg_tagged,
                nb_native,
                nb_tagged,
            )
            desired_mode = "tagged" if fg_tagged else "access"
            mismatches.append(
                {
                    "switch": switch.name,
                    "port": port_name,
                    "netbox_interface_id": nb_iface_id,
                    "netbox_interface_name": nb_port.get("name"),
                    "desired_mode": desired_mode,
                    "desired_native_vid": fg_native,
                    "desired_tagged_vids": fg_tagged,
                }
            )
        else:
            logger.info(
                "VLANs match for %s/%s (NetBox iface=%s, mode=%s, native_vid=%s, tagged_vids=%s)",
                switch.name,
                port_name,
                nb_port.get("name"),
                nb_mode,
                fg_native,
                fg_tagged,
            )

    return mismatches
