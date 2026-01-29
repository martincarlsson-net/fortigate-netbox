from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class SwitchPort:
    """
    Normalized representation of a FortiGate-managed switch port.

    VLANs are stored by name, not VID.
    - native_vlan: untagged/native VLAN
    - allowed_vlans: tagged VLANs only (or ["*"] for tagged-all/allowed-vlans-all)
    """

    name: str
    native_vlan: Optional[str]
    allowed_vlans: List[str]


@dataclass
class Switch:
    """Normalized representation of a managed switch."""

    name: str
    ports: Dict[str, SwitchPort]  # key = port name
