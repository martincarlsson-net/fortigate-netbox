import logging
from typing import Any, Dict, List

import requests

from .models import Switch, SwitchPort

logger = logging.getLogger(__name__)


class FortiGateClient:
    """
    Minimal FortiGate client for:
    - Fetching managed switch data
    - Normalizing it into Switch/SwitchPort models
    """

    def __init__(self, host: str, api_token: str, verify_ssl: bool = True) -> None:
        self.base_url = f"https://{host}"
        self.session = requests.Session()
        self.session.verify = verify_ssl
        # FortiOS token via header (preferred)
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        logger.info("Requesting FortiGate endpoint %s", url)
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_managed_switches_raw(self) -> Dict[str, Any]:
        """
        GET /api/v2/cmdb/switch-controller/managed-switch/

        Returns the raw JSON from FortiGate.
        """
        return self._get("/api/v2/cmdb/switch-controller/managed-switch/")

    @staticmethod
    def _normalize_vlan_names(port: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract native VLAN and allowed VLANs from a FortiGate port dict.

        Rules:
        - native_vlan: from "vlan" only (string, e.g. "vlan90"). Do not use
          "untagged-vlans"; that can differ from the port's native VLAN.
        - allowed_vlans:
          - If "allowed-vlans-all" == "enable": ["*"] (all VLANs allowed).
          - Else: "allowed-vlans[].vlan-name". If empty and we have a
            native_vlan, treat as access port: allowed_vlans = [native_vlan].
        """
        vlan_field = port.get("vlan")
        native_name = vlan_field if isinstance(vlan_field, str) and vlan_field else None

        allowed_vlans: List[str] = []
        if port.get("allowed-vlans-all") == "enable":
            # "all VLANs allowed" – cannot easily compare to NetBox,
            # but we use a sentinel so validator can log a warning.
            allowed_vlans = ["*"]
        else:
            allowed_list = port.get("allowed-vlans") or []
            for item in allowed_list:
                name = item.get("vlan-name") or item.get("name")
                if name:
                    allowed_vlans.append(name)

        if not allowed_vlans and native_name:
            # Typical access port: only one untagged/native VLAN
            allowed_vlans = [native_name]

        return {
            "native_vlan": native_name,
            "allowed_vlans": allowed_vlans,
        }

    def get_switches(self) -> List[Switch]:
        """
        Convert FortiGate response into internal Switch objects using
        the real-world JSON sample structure.
        """
        data = self.get_managed_switches_raw()
        results = data.get("results") or []
        switches: List[Switch] = []

        for sw in results:
            # The switch identifier in the sample is "switch-id"
            name = sw.get("switch-id") or sw.get("q_origin_key")
            if not name:
                logger.warning("Skipping switch with no 'switch-id': %s", sw)
                continue

            ports_dict: Dict[str, SwitchPort] = {}
            ports_raw = sw.get("ports") or []
            for p in ports_raw:
                port_name = p.get("port-name") or p.get("name")
                if not port_name:
                    continue

                vlan_info = self._normalize_vlan_names(p)
                port_model = SwitchPort(
                    name=port_name,
                    native_vlan=vlan_info["native_vlan"],
                    allowed_vlans=list(vlan_info["allowed_vlans"]),
                )
                ports_dict[port_name] = port_model

            switches.append(Switch(name=name, ports=ports_dict))

        return switches

