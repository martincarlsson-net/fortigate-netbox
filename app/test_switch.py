import logging
import sys
from typing import Dict, Tuple

from .config import Settings
from .fortigate_client import FortiGateClient
from .models import Switch
from .netbox_client import NetBoxClient
from .vlan_validator import _extract_netbox_vlan_info

logger = logging.getLogger(__name__)


def _find_switch_on_any_fortigate(settings: Settings, switch_name: str) -> Tuple[str, Switch]:
    """
    Search across all configured FortiGates for a switch with the given name.

    Returns a tuple of (fortigate_name, Switch).
    Raises RuntimeError if not found on any FortiGate.
    """
    for fg in settings.fortigate_devices:
        logger.info("Searching for switch %s on FortiGate %s (%s)", switch_name, fg.name, fg.host)
        client = FortiGateClient(host=fg.host, api_token=fg.api_token, verify_ssl=fg.verify_ssl)
        switches = client.get_switches()
        for sw in switches:
            if sw.name == switch_name:
                logger.info("Found switch %s on FortiGate %s", switch_name, fg.name)
                return fg.name, sw

    raise RuntimeError(f"Switch '{switch_name}' not found on any configured FortiGate.")


def run_single_switch_test(settings: Settings, switch_name: str) -> int:
    """
    Dry-run comparison for a single switch:
    - Downloads switch config from FortiGate HTTPS API.
    - Looks up the same switch in NetBox.
    - For each interface, prints FortiGate vs NetBox VLAN information.

    No changes are written to NetBox.
    """
    logger.info("Running single-switch test for %s", switch_name)

    try:
        fortigate_name, fg_switch = _find_switch_on_any_fortigate(settings, switch_name)
    except Exception as exc:  # noqa: BLE001
        logger.error("%s", exc)
        print(str(exc), file=sys.stderr)
        return 1

    nb_client = NetBoxClient(settings.netbox_url, settings.netbox_api_token)

    device = nb_client.get_device_by_name(switch_name)
    if not device:
        msg = f"Switch '{switch_name}' not found in NetBox."
        logger.error(msg)
        print(msg, file=sys.stderr)
        return 1

    interfaces = nb_client.get_interfaces_for_device(device_id=device["id"])

    # Build NetBox VLAN info mapping and make it case-insensitive on port name.
    nb_vlan_map = _extract_netbox_vlan_info(interfaces)

    nb_by_norm: Dict[str, Tuple[str, dict]] = {}
    for iface_name, info in nb_vlan_map.items():
        if not iface_name:
            continue
        nb_by_norm[iface_name.lower()] = (iface_name, info)

    print(f"=== FortiGate vs NetBox VLAN comparison for switch {switch_name} (FortiGate: {fortigate_name}) ===")

    for port_name, fg_port in fg_switch.ports.items():
        norm = port_name.lower()
        nb_entry = nb_by_norm.get(norm)
        if not nb_entry:
            print(f"[MISSING] FG port '{port_name}': no matching NetBox interface (considering case-insensitive match).")
            continue

        nb_name, nb_info = nb_entry

        fg_native = fg_port.native_vlan
        fg_allowed = sorted(fg_port.allowed_vlans)

        nb_native = nb_info["native_vlan"]
        nb_allowed = nb_info["allowed_vlans"]

        print(
            f"Port FG '{port_name}' vs NB '{nb_name}': "
            f"FG native={fg_native}, allowed={fg_allowed} | "
            f"NB native={nb_native}, allowed={nb_allowed}"
        )

    return 0

