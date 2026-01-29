import logging
from typing import Any, Dict, List

import requests

from .models import Switch, SwitchPort
from .cache_manager import CacheManager


logger = logging.getLogger(__name__)
import json
from typing import Optional


class FortiGateClient:
    """
    Minimal FortiGate client for:
    - Fetching managed switch data
    - Normalizing it into Switch/SwitchPort models
    """
    def __init__(
        self, 
        host: str, 
        username: str, 
        password: str, 
        verify_ssl: bool = True, 
        cache_manager: Optional[CacheManager] = None
    ):
        self.host = host
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.cache_manager = cache_manager
        self.base_url = f"https://{host}"
        self.session = None
        self.logger = logging.getLogger(f"{__name__}.{host}")
    
    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        logger.info("Requesting FortiGate endpoint %s", url)
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()



    def get_managed_switches(self) -> list[dict]:
        """Get all managed FortiSwitch devices with caching support."""
        cache_key = f"fortigate_{self.host}_managed_switches"
        
        # Try to get from cache first
        if self.cache_manager:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data is not None:
                self.logger.info(f"Using cached FortiSwitch data for {self.host}")
                return cached_data
        
        # Make API call
        self.logger.info(f"Fetching FortiSwitch data from {self.host} API")
        response = self.session.get(
            f"{self.base_url}/api/v2/monitor/switch-controller/managed-switch/select",
            verify=self.verify_ssl
        )
        response.raise_for_status()
        data = response.json()
        
        switches = data.get("results", [])
        
        # Cache the result
        if self.cache_manager:
            self.cache_manager.set(cache_key, switches)
        
        return switches
        # Make API call
        self.logger.info(f"Fetching FortiSwitch data from {self.host} API")
        response = self.session.get(
            f"{self.base_url}/api/v2/monitor/switch-controller/managed-switch/select",
            verify=self.verify_ssl
        )
        response.raise_for_status()
        data = response.json()
        
        switches = data.get("results", [])
        
        # Cache the result
        if self.cache_manager:
            self.cache_manager.set(cache_key, switches)
        
        return switches

    @staticmethod
    def _normalize_vlan_names(self, ports: list[dict]) -> list[dict]:
        """
        Normalize VLAN names to match NetBox format.
        
        Args:
            ports: List of port dictionaries from FortiGate
            
        Returns:
            List of normalized port dictionaries
        """
        normalized = []
        
        for i, port in enumerate(ports):
            # DEBUG: Print full port dictionary for first port
            if i == 0:
                self.logger.info(f"First port full dictionary: {json.dumps(port, indent=2)}")
            
            normalized_port = {
                'name': port.get('port-name', ''),
                'description': port.get('description', ''),
                'enabled': port.get('status', 'down') == 'up',
                'type': port.get('type', 'physical'),
            }
            
            # Get native VLAN from the 'vlan' field (NOT from untagged-vlans)
            native_vlan_name = port.get('vlan', '')
            if native_vlan_name:
                # Convert vlan90 -> VLAN-90 format
                if native_vlan_name.startswith('vlan') and native_vlan_name[4:].isdigit():
                    vlan_id = native_vlan_name[4:]
                    normalized_port['native_vlan'] = f"VLAN-{vlan_id}"
                else:
                    normalized_port['native_vlan'] = native_vlan_name
            
            # Get allowed VLANs from allowed-vlans array
            allowed_vlans = []
            for vlan_obj in port.get('allowed-vlans', []):
                vlan_name = vlan_obj.get('vlan-name', '')
                if vlan_name:
                    # Convert vlan90 -> VLAN-90 format
                    if vlan_name.startswith('vlan') and vlan_name[4:].isdigit():
                        vlan_id = vlan_name[4:]
                        allowed_vlans.append(f"VLAN-{vlan_id}")
                    else:
                        allowed_vlans.append(vlan_name)
            
            normalized_port['allowed_vlans'] = allowed_vlans
            normalized.append(normalized_port)
        
        return normalized

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

