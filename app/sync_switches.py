import logging
import sys
from typing import List, Optional

from .config import Settings
from .fortigate_client import FortiGateClient
from .models import Switch, SwitchPort
from .netbox_client import NetBoxClient
from .storage import clear_data_dir, load_all_switches, save_switches_for_device
from .vlan_validator import validate_switch_vlans

logger = logging.getLogger(__name__)


def _switch_from_dict(data: dict) -> Switch:
    """Reconstruct a Switch model from the stored JSON structure."""
    ports: List[dict] = data.get("ports") or []
    return Switch(
        name=data["name"],
        ports={
            p["name"]: SwitchPort(
                name=p["name"],
                native_vlan=p.get("native_vlan"),
                allowed_vlans=list(p.get("allowed_vlans") or []),
            )
            for p in ports
        },
    )


def run_sync(settings: Settings, *, only_switch_name: Optional[str] = None) -> int:
    """
    Main synchronization flow:
    1) Clear stored data.
    2) Fetch managed switches from each FortiGate and store JSON.
    3) Iterate stored switches and compare VLANs with NetBox.

    Behavior:
    - If only_switch_name is provided, only that switch is validated.
    - If a switch cannot be found in NetBox (by name), stop execution and
      print concise details about the missing switch.
    - No changes are made to NetBox; only validation and reporting.
    """
    # 1) Clear data dir for a fresh daily snapshot
    clear_data_dir(settings.sync_data_dir)

    # 2) Retrieve from all FortiGates and store JSON
    for fg in settings.fortigate_devices:
        logger.info("Processing FortiGate %s (%s)", fg.name, fg.host)
        client = FortiGateClient(
            host=fg.host,
            api_token=fg.api_token,
            verify_ssl=fg.verify_ssl,
        )
        try:
            switches: List[Switch] = client.get_switches()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to retrieve switches from FortiGate %s (%s): %s",
                fg.name,
                fg.host,
                exc,
            )
            return 1

        # If requested, only store the matching switch (case-sensitive match on name).
        if only_switch_name:
            switches = [sw for sw in switches if sw.name == only_switch_name]
            if not switches:
                logger.info(
                    "TEST_SWITCH=%s: no matching switches found on FortiGate %s",
                    only_switch_name,
                    fg.name,
                )

        save_switches_for_device(settings.sync_data_dir, fg.name, switches)

    # 3) Iterate stored switches and compare with NetBox
    switches_raw = load_all_switches(settings.sync_data_dir)

    # If requested, filter stored switches as well (defensive if storage ever changes).
    if only_switch_name:
        switches_raw = [sw for sw in switches_raw if sw.get("name") == only_switch_name]

        if not switches_raw:
            logger.error(
                "Switch %s not found on any configured FortiGate (after collection).",
                only_switch_name,
            )
            print(
                f"Switch not found on any FortiGate: name={only_switch_name}",
                file=sys.stderr,
            )
            return 1

    nb_client = NetBoxClient(settings.netbox_url, settings.netbox_api_token)

    for sw_dict in switches_raw:
        switch_name = sw_dict.get("name")
        if not switch_name:
            logger.warning("Encountered stored switch without a name: %s", sw_dict)
            continue

        device = nb_client.get_device_by_name(switch_name)
        if not device:
            # Stop execution if switch doesn't exist in NetBox
            logger.error(
                "Switch %s not found in NetBox. Stopping execution.",
                switch_name,
            )
            print(
                f"Missing switch in NetBox: name={switch_name}",
                file=sys.stderr,
            )
            return 1

        interfaces = nb_client.get_interfaces_for_device(device_id=device["id"])

        switch_obj = _switch_from_dict(sw_dict)

        # VLAN validation (no writes to NetBox)
        validate_switch_vlans(switch_obj, interfaces)

    return 0
