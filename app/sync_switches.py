import logging
import sys
from typing import List, Optional

from .config import Settings
from .fortigate_client import FortiGateClient
from .models import Switch
from .netbox_client import NetBoxClient
from .vlan_validator import validate_switch_vlans
from .cache_manager import CacheManager

logger = logging.getLogger(__name__)


def run_sync(settings: Settings, *, only_switch_name: Optional[str] = None) -> int:
    """
    Main synchronization flow:
    - Retrieve managed switches from each FortiGate.
    - For each switch, compare VLANs with NetBox.

    Behavior:
    - If only_switch_name is provided, only that switch is validated.
    - If a switch cannot be found in NetBox (by name), stop execution and
      print concise details about the missing switch.
    - No changes are made to NetBox; only validation and reporting.

    Notes:
    - This module no longer uses storage.py snapshots; it operates directly
      against the live FortiGate + NetBox APIs.
    """

    nb_client = NetBoxClient(settings.netbox_url, settings.netbox_api_token)

    matched_any = False

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

        if only_switch_name:
            switches = [sw for sw in switches if sw.name == only_switch_name]

        for sw in switches:
            matched_any = True

            device = nb_client.get_device_by_name(sw.name)
            if not device:
                logger.error("Switch %s not found in NetBox. Stopping execution.", sw.name)
                print(f"Missing switch in NetBox: name={sw.name}", file=sys.stderr)
                return 1

            interfaces = nb_client.get_interfaces_for_device(device_id=device["id"])
            validate_switch_vlans(sw, interfaces)

    if only_switch_name and not matched_any:
        logger.error("Switch %s not found on any configured FortiGate.", only_switch_name)
        print(f"Switch not found on any FortiGate: name={only_switch_name}", file=sys.stderr)
        return 1

    return 0
