import logging
from typing import Any, Dict, List, Optional
import requests
from .cache_manager import CacheManager
import time
from requests.exceptions import ReadTimeout, ConnectionError
logger = logging.getLogger(__name__)


class NetBoxClient:
    """Thin wrapper around the NetBox REST API (read + limited write operations)."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: int = 120,
        verify_ssl: bool = True,
        cache_manager: Optional[CacheManager] = None,
    ):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.verify_ssl = verify_ssl
        self.cache_manager = cache_manager
        self.default_timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                'Authorization': f'Token {token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        self.logger = logging.getLogger(__name__)

        # Safety: VLAN lookups should be quick and should not block the whole run for minutes.
        self.vlan_lookup_timeout_seconds = 20

    def _get(
        self,
        endpoint: str,
        params: dict = None,
        max_retries: int = 3,
        timeout: Optional[int] = None,
    ) -> dict:
        """Make a GET request to NetBox API with retry logic."""
        url = f"{self.base_url}{endpoint}"
        params = params or {}

        for attempt in range(max_retries):
            try:
                effective_timeout = (timeout or self.default_timeout) + (attempt * 30)

                resp = self.session.get(
                    url,
                    params=params,
                    verify=self.verify_ssl,
                    timeout=effective_timeout,
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

    def _patch(self, endpoint: str, payload: dict, *, timeout: Optional[int] = None) -> dict:
        """PATCH to NetBox API and return JSON response."""
        url = f"{self.base_url}{endpoint}"
        resp = self.session.patch(
            url,
            json=payload,
            verify=self.verify_ssl,
            timeout=timeout or self.default_timeout,
        )
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

        # Make API call with pagination
        self.logger.info("Fetching devices from NetBox API")
        devices = []
        url = f"{self.base_url}/api/dcim/devices/"

        while url:
            response = self.session.get(url, verify=self.verify_ssl, timeout=self.default_timeout)
            response.raise_for_status()
            data = response.json()
            devices.extend(data.get("results", []))
            url = data.get("next")  # Get next page URL

        # Cache the result
        if self.cache_manager:
            self.cache_manager.set(cache_key, devices)

        return devices

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

    def get_interface(self, interface_id: int) -> dict:
        """Get a single interface by ID (fresh read, no cache)."""
        if not isinstance(interface_id, int):
            raise RuntimeError("interface_id must be an integer")
        return self._get(f"/api/dcim/interfaces/{interface_id}/")

    def get_interfaces_for_device(self, device_id: int) -> list[dict]:
        """Get all interfaces for a specific device with caching support."""
        cache_key = f"netbox_device_{device_id}_interfaces"

        # Try cache first (only if use_cache=True)
        if self.cache_manager:
            cached_data = self.cache_manager.get(cache_key)
            if cached_data is not None:
                self.logger.info(f"✅ Using cached interfaces for device {device_id}")
                return cached_data

        # Cache miss or use_cache=False: fetch from API
        self.logger.info(f"🔄 Fetching interfaces from NetBox API for device {device_id}...")
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

        # ALWAYS cache the result (even if use_cache=False)
        if self.cache_manager:
            self.cache_manager.set(cache_key, interfaces)

        self.logger.info(f"✅ Fetched {len(interfaces)} interfaces for device {device_id}")
        return interfaces

    def get_vlan_id_by_vid(self, vid: int) -> int:
        """Resolve a VLAN vid (e.g. 90) to a NetBox VLAN object ID."""
        if not isinstance(vid, int):
            raise RuntimeError(f"VLAN vid must be int, got: {vid!r}")
        if vid <= 0:
            raise RuntimeError(f"VLAN vid must be > 0, got: {vid}")

        cache_key = f"netbox_vlan_id_vid_{vid}"
        if self.cache_manager:
            cached = self.cache_manager.get(cache_key)
            if isinstance(cached, int):
                return cached

        self.logger.info("Resolving NetBox VLAN id for vid=%s", vid)
        data = self._get(
            "/api/ipam/vlans/",
            params={"vid": vid},
            timeout=self.vlan_lookup_timeout_seconds,
        )
        results = data.get("results", [])
        if not results:
            raise RuntimeError(f"NetBox VLAN not found by vid: {vid}")
        if len(results) > 1:
            raise RuntimeError(
                f"Multiple NetBox VLANs found with vid={vid}; please scope VLANs or make vids unique."
            )

        vlan_id = results[0].get("id")
        if not isinstance(vlan_id, int):
            raise RuntimeError(f"NetBox returned VLAN without integer id for vid={vid}")

        if self.cache_manager:
            self.cache_manager.set(cache_key, vlan_id)

        return vlan_id

    def update_interface_vlan_config(
        self,
        *,
        interface_id: int,
        mode: str,
        native_vlan_vid: Optional[int],
        tagged_vlan_vids: List[int],
    ) -> dict:
        """
        Update a NetBox interface VLAN config so it matches FortiGate.

        - mode: 'access' or 'tagged'
        - native VLAN sets untagged_vlan
        - tagged VLANs set tagged_vlans (list of VLAN IDs); cleared in access mode

        Notes:
        - This method resolves VLAN object IDs by querying NetBox using vlan vid.
        """
        if not isinstance(interface_id, int):
            raise RuntimeError("interface_id must be an integer")

        mode_value = (mode or "").strip().lower()
        if mode_value not in {"access", "tagged"}:
            raise RuntimeError(f"Unsupported NetBox interface mode for update: {mode!r}")

        untagged_vlan_id = None
        if native_vlan_vid is not None:
            self.logger.info("Resolving untagged VLAN: vid=%s", native_vlan_vid)
            untagged_vlan_id = self.get_vlan_id_by_vid(native_vlan_vid)

        tagged_vlan_ids: List[int] = []
        for vv in tagged_vlan_vids:
            self.logger.info("Resolving tagged VLAN: vid=%s", vv)
            tagged_vlan_ids.append(self.get_vlan_id_by_vid(vv))

        payload = {
            "mode": mode_value,
            "untagged_vlan": untagged_vlan_id,
            "tagged_vlans": tagged_vlan_ids if mode_value == "tagged" else [],
        }

        self.logger.warning(
            "Updating NetBox interface %s VLANs: mode=%s untagged_vid=%s tagged_vids=%s",
            interface_id,
            mode_value,
            native_vlan_vid,
            tagged_vlan_vids,
        )

        return self._patch(f"/api/dcim/interfaces/{interface_id}/", payload)
