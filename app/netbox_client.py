import logging
from typing import Any, Dict, List, Optional
from cache_manager import CacheManager
import requests

logger = logging.getLogger(__name__)


class NetBoxClient:
    """Thin wrapper around the NetBox REST API for read-only operations."""

    def __init__(self, base_url: str, token: str, verify_ssl: bool = True, cache_manager: Optional[CacheManager] = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.cache_manager = cache_manager
        self.session.headers.update(
            {
                "Authorization": f"Token {api_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        logger.debug("NetBox GET %s params=%s", url, params)
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_all_devices(self) -> list[dict]:
        """Get all devices from NetBox with caching support."""
        cache_key = "netbox_all_devices"
        
        # Try to get from cache first
        if self.cache_manager:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data is not None:
                self.logger.info("Using cached NetBox devices data")
                return cached_data
        
        # Make API call
        self.logger.info("Fetching devices from NetBox API")
        devices = []
        offset = 0
        limit = 1000
        
        while True:
            data = self._get("/api/dcim/devices/", params={"limit": limit, "offset": offset})
            devices.extend(data.get("results", []))
            
            if not data.get("next"):
                break
            offset += limit
        
        # Cache the result
        if self.cache_manager:
            self.cache_manager.set(cache_key, devices)
        
        return devices


       
    def get_interfaces_for_device(self, device_id: int) -> list[dict]:
        """Get all interfaces for a specific device with caching support."""
        cache_key = f"netbox_device_{device_id}_interfaces"
        
        # Try to get from cache first
        if self.cache_manager:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data is not None:
                self.logger.info(f"Using cached NetBox interfaces data for device {device_id}")
                return cached_data
        
        # Make API call
        self.logger.info(f"Fetching interfaces from NetBox API for device {device_id}")
        interfaces = []
        offset = 0
        limit = 1000
        
        while True:
            data = self._get(
                "/api/dcim/interfaces/",
                params={"device_id": device_id, "limit": limit, "offset": offset}
            )
            interfaces.extend(data.get("results", []))
            
            if not data.get("next"):
                break
            offset += limit
        
        # Cache the result
        if self.cache_manager:
            self.cache_manager.set(cache_key, interfaces)
        
        return interfaces 
    def get_device_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Look up a device by its exact name.

        Assumes unique device names. Returns the first match or None.
        """
        data = self._get("/api/dcim/devices/", params={"name": name})
        results = data.get("results", [])
        if not results:
            return None
        if len(results) > 1:
            logger.warning(
                "Multiple NetBox devices found with name '%s'; using the first.", name
            )
        return results[0]

    def get_interfaces_for_device(self, device_id: int) -> List[Dict[str, Any]]:
        """
        Fetch all interfaces for a given device ID.
        The returned interface dicts should include untagged_vlan/tagged_vlans
        if NetBox is configured to expose related objects.
        """
        data = self._get(
            "/api/dcim/interfaces/", params={"device_id": device_id, "limit": 0}
        )
        return data.get("results", [])

