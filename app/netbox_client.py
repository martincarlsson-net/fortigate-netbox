import logging
from typing import Any, Dict, List, Optional
from cache_manager import CacheManager
import requests
from typing import Optional
from app.cache_manager import CacheManager  # Correct import path
import time
from requests.exceptions import ReadTimeout, ConnectionError
logger = logging.getLogger(__name__)


class NetBoxClient:
    """Thin wrapper around the NetBox REST API for read-only operations."""
    def __init__(
        self, 
        base_url: str, 
        token: str, 
        verify_ssl: bool = True, 
        cache_manager: Optional[CacheManager] = None
    ):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.verify_ssl = verify_ssl
        self.cache_manager = cache_manager
        self.default_timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Token {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        self.logger = logging.getLogger(__name__)
    
    def _get(self, endpoint: str, params: dict = None, max_retries: int = 3) -> dict:
        """Make a GET request to NetBox API with retry logic."""
        url = f"{self.base_url}{endpoint}"
        params = params or {}
        
        for attempt in range(max_retries):
            try:
                timeout = self.default_timeout + (attempt * 30)  # Increase timeout on each retry
                
                resp = self.session.get(
                    url, 
                    params=params, 
                    verify=self.verify_ssl,
                    timeout=timeout
                )
                resp.raise_for_status()
                return resp.json()
                
            except ReadTimeout:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    self.logger.warning(
                        f"Timeout (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {wait_time}s... URL: {endpoint}"
                    )
                    time.sleep(wait_time)
                else:
                    self.logger.error(f"Failed after {max_retries} attempts for {endpoint}")
                    raise
            except ConnectionError:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    self.logger.warning(
                        f"Connection error (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    raise
    

    def get_all_devices(self) -> list[dict]:
        """Get all devices from NetBox with caching support."""
        cache_key = "netbox_all_devices"
        
        # Try to get from cache first
        if self.cache_manager:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data is not None:
                self.logger.info("Using cached NetBox devices data")
                return cached_data
        
        # Make API call with pagination
        self.logger.info("Fetching devices from NetBox API")
        devices = []
        url = f"{self.base_url}/api/dcim/devices/"
        
        while url:
            response = self.session.get(url, verify=self.verify_ssl, timeout=30)
            response.raise_for_status()
            data = response.json()
            devices.extend(data.get("results", []))
            url = data.get("next")  # Get next page URL
        
        # Cache the result
        if self.cache_manager:
            self.cache_manager.set(cache_key, devices)
        
        return devices

        
    def get_interfaces_for_device(self, device_id: int) -> list[dict]:
        """Get all interfaces for a specific device with caching support."""
        cache_key = f"netbox_device_{device_id}_interfaces"
        
        # Try cache first
        if self.cache_manager:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data is not None:
                self.logger.info(f"✅ Using cached interfaces for device {device_id}")
                return cached_data
        
        # Make API call
        self.logger.info(f"🔄 Fetching interfaces from NetBox for device {device_id}...")
        interfaces = []
        offset = 0
        limit = 100
        
        while True:
            params = {
                "device_id": device_id,
                "limit": limit,
                "offset": offset,
            }
            
            self.logger.debug(f"  Fetching batch: offset={offset}, limit={limit}")
            data = self._get("/api/dcim/interfaces/", params=params)
            
            results = data.get("results", [])
            interfaces.extend(results)
            
            if not data.get("next"):
                break
            
            offset += limit
        
        # Cache the result
        if self.cache_manager:
            self.cache_manager.set(cache_key, interfaces)
        
        self.logger.info(f"✅ Fetched {len(interfaces)} interfaces for device {device_id}")
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

