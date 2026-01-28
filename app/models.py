from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class SwitchPort:
    """
    Normalized representation of a FortiGate-managed switch port.

    For v1 we model VLANs by name, not VID, because the FortiGate
    JSON uses VLAN object names (e.g. "quarantine", "vlan50").
    """

    name: str
    native_vlan: Optional[str]
    allowed_vlans: List[str]


@dataclass
class Switch:
    """Normalized representation of a managed switch."""

    name: str
    ports: Dict[str, SwitchPort]  # key = port name

