import json
import logging
import re
from typing import Any, Dict, List, Optional

import requests

from .cache_manager import CacheManager
from .models import Switch, SwitchPort

logger = logging.getLogger(__name__)

import urllib3
# disable insecure HTTPS warnings (self-signed certs)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class FortiGateClient:
    """Minimal FortiGate client for retrieving managed switch data."""

    def __init__(
        self,
        name: str,
        host: str,
        api_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_ssl: bool = True,
        cache_manager: Optional[CacheManager] = None,
        vlan_translations: Optional[Dict[str, int]] = None,
    ):
        self.name = name
        self.host = host
        self.verify_ssl = verify_ssl
        self.cache_manager = cache_manager
        self.vlan_translations: Dict[str, int] = vlan_translations or {}
        self.base_url = f"https://{host}".rstrip("/")

        self.session = requests.Session()

        # Auth: prefer API token if provided.
        if api_token:
            # FortiGate REST API tokens are typically sent as an Authorization header.
            self.session.headers.update({"Authorization": f"Bearer {api_token}"})
        elif username and password:
            self.session.auth = (username, password)

        self.logger = logging.getLogger(f"{__name__}.{host}")

    def get_managed_switches_raw(self) -> Dict[str, Any]:
        """Return the raw FortiGate response for managed switches.

        This keeps compatibility with earlier code that expected a dict
        containing a top-level `results` key.
        """
        cache_key = f"fortigate_{self.name}_{self.host}_managed_switches_raw"

        if self.cache_manager:
            cached = self.cache_manager.get(cache_key)
            if cached is not None:
                self.logger.info("Using cached FortiSwitch raw data for %s", self.host)
                return cached

        self.logger.info("Fetching FortiSwitch raw data from %s API", self.host)
        resp = self.session.get(
            f"{self.base_url}/api/v2/cmdb/switch-controller/managed-switch/",
            verify=self.verify_ssl,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if self.cache_manager:
            self.cache_manager.set(cache_key, data)

        return data

    @staticmethod
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
        return None

    def _translate_vlan_to_vid(self, name: Optional[str]) -> Optional[int]:
        """Translate FortiGate VLAN names to NetBox VLAN vid (integer)."""
        if not name:
            return None
        raw = str(name).strip()

        # Allow mapping in terms of raw FortiGate name (e.g. "_default": 1)
        if raw in self.vlan_translations:
            return self.vlan_translations[raw]

        # Fallback: parse vlan vid from the string itself
        return self._extract_vlan_vid(raw)

    def _normalize_port_vlans(self, port: Dict[str, Any]) -> Dict[str, Any]:
        """Extract native + tagged VLAN vids from a FortiGate port dict.

        Mapping:
          - native_vlan: from 'vlan' field
          - allowed_vlans: tagged VLANs from 'allowed-vlans' (excluding native_vlan)
          - allowed-vlans-all=enable => allowed_vlans=["*"] (tagged-all)
        """

        # Native VLAN from 'vlan' field
        native_vlan = self._translate_vlan_to_vid(port.get("vlan"))

        # Tagged-all: allowed-vlans-all=enable
        if str(port.get("allowed-vlans-all", "")).strip().lower() == "enable":
            return {"native_vlan": native_vlan, "allowed_vlans": ["*"]}

        # Tagged VLANs: allowed-vlans (excluding native)
        tagged_vlans: List[int] = []
        for vlan_obj in port.get("allowed-vlans", []) or []:
            if not isinstance(vlan_obj, dict):
                continue
            vlan_name = vlan_obj.get("vlan-name")
            if not isinstance(vlan_name, str) or not vlan_name:
                continue
            norm = self._translate_vlan_to_vid(vlan_name)
            if isinstance(norm, int) and norm != native_vlan:
                tagged_vlans.append(norm)

        return {"native_vlan": native_vlan, "allowed_vlans": tagged_vlans}

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

                vlan_info = self._normalize_port_vlans(p)
                port_model = SwitchPort(
                    name=port_name,
                    native_vlan=vlan_info.get("native_vlan"),
                    allowed_vlans=list(vlan_info.get("allowed_vlans", [])),
                )
                ports_dict[port_name] = port_model

            switches.append(Switch(name=name, ports=ports_dict))

        return switches
