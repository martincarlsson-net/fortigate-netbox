import logging
import sys
from pathlib import Path
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
    - In normal mode: no changes are made to NetBox; only validation and reporting.
    - In TEST_SWITCH mode (only_switch_name is set): NetBox VLAN updates may be applied,
      limited by runtime.max_netbox_updates, then the program stops (kill-switch).
    - After each PATCH, the device interface cache is invalidated and the updated interface
      is re-read to verify the change was applied.

    Notes:
    - This module no longer uses storage.py snapshots; it operates directly
      against the live FortiGate + NetBox APIs.
    """

    # Initialize cache manager
    cache_manager = CacheManager(
        cache_dir=Path(settings.cache_dir),
        use_cache=settings.use_cached_data,
    )

    # Initialize NetBox client with timeout and cache manager
    nb_client = NetBoxClient(
        base_url=settings.netbox_url,
        token=settings.netbox_api_token,
        timeout=settings.netbox_timeout,
        cache_manager=cache_manager,
    )

    matched_any = False

    for fg in settings.fortigate_devices:
        logger.info("Processing FortiGate %s (%s)", fg.name, fg.host)
        client = FortiGateClient(
            host=fg.host,
            api_token=fg.api_token,
            verify_ssl=fg.verify_ssl,
            vlan_translations=settings.vlan_translations,
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

            device_id = device["id"]
            interfaces = nb_client.get_interfaces_for_device(device_id=device_id)
            mismatches = validate_switch_vlans(sw, interfaces)

            # Kill-switch: only apply NetBox updates in TEST_SWITCH mode, then stop after N updates.
            if only_switch_name and mismatches:
                interfaces_cache_key = f"netbox_device_{device_id}_interfaces"

                max_updates = int(getattr(settings, "max_netbox_updates", 1))
                if max_updates <= 0:
                    logger.warning(
                        "TEST_SWITCH mode active, but max_netbox_updates=%s; no NetBox updates will be performed.",
                        max_updates,
                    )
                    return 0

                applied = 0
                for m in mismatches:
                    iface_id = m.get("netbox_interface_id")
                    if not isinstance(iface_id, int):
                        logger.error(
                            "Skipping NetBox update for %s/%s: missing NetBox interface id (got %r)",
                            sw.name,
                            m.get("port"),
                            iface_id,
                        )
                        continue

                    nb_client.update_interface_vlan_config(
                        interface_id=iface_id,
                        mode=str(m.get("desired_mode") or "tagged"),
                        native_vlan_vid=m.get("desired_native_vid"),
                        tagged_vlan_vids=list(m.get("desired_tagged_vids") or []),
                    )

                    # Invalidate cached device interfaces so subsequent reads reflect the update.
                    if cache_manager:
                        cache_manager.delete(interfaces_cache_key)

                    # Optional verification: re-read the updated interface and confirm desired state.
                    updated_iface = nb_client.get_interface(iface_id)
                    updated_mode = (updated_iface.get("mode") or {}).get("value")
                    untagged = updated_iface.get("untagged_vlan") or {}
                    updated_native_vid = untagged.get("vid")
                    tagged = updated_iface.get("tagged_vlans") or []
                    updated_tagged_vids = sorted(
                        [v.get("vid") for v in tagged if isinstance(v, dict) and isinstance(v.get("vid"), int)]
                    )

                    desired_mode = str(m.get("desired_mode") or "tagged")
                    desired_native_vid = m.get("desired_native_vid")
                    desired_tagged_vids = sorted(list(m.get("desired_tagged_vids") or []))

                    if (
                        str(updated_mode).lower() != desired_mode.lower()
                        or updated_native_vid != desired_native_vid
                        or updated_tagged_vids != desired_tagged_vids
                    ):
                        logger.error(
                            "Post-update verification failed for %s/%s (iface=%s): "
                            "desired mode=%s native_vid=%s tagged_vids=%s, "
                            "got mode=%s native_vid=%s tagged_vids=%s",
                            sw.name,
                            m.get("port"),
                            iface_id,
                            desired_mode,
                            desired_native_vid,
                            desired_tagged_vids,
                            updated_mode,
                            updated_native_vid,
                            updated_tagged_vids,
                        )
                    else:
                        logger.info(
                            "Post-update verification OK for %s/%s (iface=%s): mode=%s native_vid=%s tagged_vids=%s",
                            sw.name,
                            m.get("port"),
                            iface_id,
                            updated_mode,
                            updated_native_vid,
                            updated_tagged_vids,
                        )

                    applied += 1

                    if applied >= max_updates:
                        logger.warning(
                            "Kill-switch active: updated %s mismatching port(s) on %s; stopping now.",
                            applied,
                            sw.name,
                        )
                        return 0

    if only_switch_name and not matched_any:
        logger.error("Switch %s not found on any configured FortiGate.", only_switch_name)
        print(f"Switch not found on any FortiGate: name={only_switch_name}", file=sys.stderr)
        return 1

    return 0
