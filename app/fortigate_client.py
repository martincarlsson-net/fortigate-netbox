import json
import logging
from typing import Any, Dict, List, Optional

import requests

from .cache_manager import CacheManager
from .models import Switch, SwitchPort

logger = logging.getLogger(__name__)


class FortiGateClient:
    """Minimal FortiGate client for retrieving managed switch data."""

    def __init__(
        self,
        host: str,
        api_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_ssl: bool = True,
        cache_manager: Optional[CacheManager] = None,
    ):
        self.host = host
        self.verify_ssl = verify_ssl
        self.cache_manager = cache_manager
        self.base_url = f"https://{host}".rstrip("/")

        self.session = requests.Session()

        # Auth: prefer API token if provided.
        if api_token:
            # FortiGate REST API tokens are typically sent as an Authorization header.
            self.session.headers.update({"Authorization": f"Bearer {api_token}"})
        elif username and password:
            self.session.auth = (username, password)

        self.logger = logging.getLogger(f"{__name__}.{host}")

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        self.logger.info("Requesting FortiGate endpoint %s", url)
        resp = self.session.get(url, timeout=15, verify=self.verify_ssl)
        resp.raise_for_status()
        return resp.json()

    def get_managed_switches_raw(self) -> Dict[str, Any]:
        """Return the raw FortiGate response for managed switches.

        This keeps compatibility with earlier code that expected a dict
        containing a top-level `results` key.
        """
        cache_key = f"fortigate_{self.host}_managed_switches_raw"

        if self.cache_manager:
            cached = self.cache_manager.get(cache_key)
            if cached is not None:
                self.logger.info("Using cached FortiSwitch raw data for %s", self.host)
                return cached

        self.logger.info("Fetching FortiSwitch raw data from %s API", self.host)
        resp = self.session.get(
            f"{self.base_url}/api/v2/monitor/switch-controller/managed-switch/select",
            verify=self.verify_ssl,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if self.cache_manager:
            self.cache_manager.set(cache_key, data)

        return data

    def get_managed_switches(self) -> list[dict]:
        """Get all managed FortiSwitch devices.

        Returns the `results` list from the raw API response.
        """
        data = self.get_managed_switches_raw()
        return data.get("results", [])

    @staticmethod
    def _normalize_port_vlans(port: Dict[str, Any]) -> Dict[str, Any]:
        """Extract native/allowed VLAN names from a FortiGate port dict."""

        # Get native VLAN from the 'vlan' field (NOT from untagged-vlans)
        native_vlan: Optional[str] = None
        native_vlan_name = port.get("vlan")
        if isinstance(native_vlan_name, str) and native_vlan_name:
            # Convert vlan90 -> VLAN-90 format
            if native_vlan_name.startswith("vlan") and native_vlan_name[4:].isdigit():
                vlan_id = native_vlan_name[4:]
                native_vlan = f"VLAN-{vlan_id}"
            else:
                native_vlan = native_vlan_name

        allowed_vlans: List[str] = []
        for vlan_obj in port.get("allowed-vlans", []) or []:
            if not isinstance(vlan_obj, dict):
                continue
            vlan_name = vlan_obj.get("vlan-name")
            if not isinstance(vlan_name, str) or not vlan_name:
                continue

            # Convert vlan90 -> VLAN-90 format
            if vlan_name.startswith("vlan") and vlan_name[4:].isdigit():
                vlan_id = vlan_name[4:]
                allowed_vlans.append(f"VLAN-{vlan_id}")
            else:
                allowed_vlans.append(vlan_name)

        return {"native_vlan": native_vlan, "allowed_vlans": allowed_vlans}

    def get_switches(self) -> List[Switch]:
        """Convert FortiGate response into internal Switch objects."""
        data = self.get_managed_switches_raw()
        results = data.get("results") or []
        switches: List[Switch] = []

        for sw in results:
            name = sw.get("switch-id") or sw.get("q_origin_key")
            if not name:
                logger.warning("Skipping switch with no 'switch-id': %s", sw)
                continue

            ports_dict: Dict[str, SwitchPort] = {}
            ports_raw = sw.get("ports") or []
            for idx, p in enumerate(ports_raw):
                if not isinstance(p, dict):
                    continue

                port_name = p.get("port-name") or p.get("name")
                if not port_name:
                    continue

                # Keep existing debug behavior: show full dict for first port of each switch.
                if idx == 0:
                    self.logger.info(
                        "First port full dictionary: %s", json.dumps(p, indent=2)
                    )

                vlan_info = self._normalize_port_vlans(p)
                port_model = SwitchPort(
                    name=port_name,
                    native_vlan=vlan_info.get("native_vlan"),
                    allowed_vlans=list(vlan_info.get("allowed_vlans", [])),
                )
                ports_dict[port_name] = port_model

            switches.append(Switch(name=name, ports=ports_dict))

        return switches
