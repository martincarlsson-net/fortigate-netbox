import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import yaml

logger = logging.getLogger(__name__)


def _normalize_netbox_url(url: str) -> str:
    """Normalize NETBOX_URL and ensure it has a host."""
    u = url.strip().rstrip("/")
    # Collapse extra slashes after :// (e.g. https:///host -> https://host)
    u = re.sub(r"(https?):///+", r"\1://", u)
    parsed = urlparse(u)
    if not parsed.netloc:
        raise RuntimeError(
            f"NETBOX_URL has no host: {url!r}. "
            "Use e.g. https://netbox.example.com (no extra slashes)."
        )
    return u


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    v = raw.strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"Invalid boolean value for {name}={raw!r} (expected true/false).")


@dataclass
class FortiGateDevice:
    name: str
    host: str  # e.g. "fg1.example.com" or "10.0.0.1"
    api_token: str
    verify_ssl: bool = True


@dataclass
class Settings:
    fortigate_devices: List[FortiGateDevice]
    netbox_url: str
    netbox_api_token: str
    netbox_timeout: int
    sync_data_dir: Path
    cache_dir: Path
    use_cached_data: bool
    vlan_translations: Dict[str, str]
    log_level: str = "INFO"
    test_switch: Optional[str] = None


def _read_secret_file(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        logger.warning("Secret file %s does not exist", p)
        return None
    return p.read_text(encoding="utf-8").strip()


def _parse_vlan_translations(raw: object) -> Dict[str, str]:
    """Parse vlan_translations from YAML (dict or null)."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        out: Dict[str, str] = {}
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, str) and k and v:
                out[k] = v
        return out
    raise RuntimeError("vlan_translations must be a mapping of fortigate_name -> netbox_name")


def _load_settings_from_yaml(path: str) -> Settings:
    """Load settings from a single YAML config file."""
    p = Path(path)
    if not p.is_file():
        raise RuntimeError(f"APP_CONFIG_FILE not found: {path}")

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to read YAML config: {path}") from exc

    if not isinstance(raw, dict):
        raise RuntimeError("YAML config root must be a mapping/object")

    # NetBox config
    netbox = raw.get("netbox") or {}
    if not isinstance(netbox, dict):
        raise RuntimeError("netbox must be a mapping/object")

    netbox_url = netbox.get("url")
    if not isinstance(netbox_url, str) or not netbox_url.strip():
        raise RuntimeError("netbox.url is required")
    netbox_url = _normalize_netbox_url(netbox_url)

    netbox_timeout = netbox.get("timeout", 120)
    try:
        netbox_timeout = int(netbox_timeout)
    except Exception as exc:
        raise RuntimeError("netbox.timeout must be an integer (seconds)") from exc

    nb_token: Optional[str] = None
    if isinstance(netbox.get("api_token"), str) and netbox["api_token"].strip():
        nb_token = netbox["api_token"].strip()
    elif isinstance(netbox.get("api_token_file"), str) and netbox["api_token_file"].strip():
        nb_token = _read_secret_file(netbox["api_token_file"].strip())
    if not nb_token:
        raise RuntimeError("netbox.api_token (or netbox.api_token_file) is required")

    # Runtime config
    runtime = raw.get("runtime") or {}
    if not isinstance(runtime, dict):
        raise RuntimeError("runtime must be a mapping/object")

    log_level = str(runtime.get("log_level", "INFO"))
    test_switch = runtime.get("test_switch")
    if test_switch is not None and not isinstance(test_switch, str):
        raise RuntimeError("runtime.test_switch must be a string or null")

    sync_data_dir = Path(str(runtime.get("sync_data_dir", "/app/data")))
    sync_data_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = Path(str(runtime.get("cache_dir", "/app/data/cache")))
    cache_dir.mkdir(parents=True, exist_ok=True)

    use_cached_data_raw = runtime.get("use_cached_data", False)
    if isinstance(use_cached_data_raw, bool):
        use_cached_data = use_cached_data_raw
    elif isinstance(use_cached_data_raw, str):
        use_cached_data = use_cached_data_raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    else:
        use_cached_data = False

    # VLAN translations
    vlan_translations = _parse_vlan_translations(raw.get("vlan_translations"))

    # FortiGate devices
    fg_list = raw.get("fortigates")
    if not isinstance(fg_list, list) or not fg_list:
        raise RuntimeError("fortigates must be a non-empty list")

    fortigate_devices: List[FortiGateDevice] = []
    for d in fg_list:
        if not isinstance(d, dict):
            continue
        name = d.get("name")
        host = d.get("host")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError("Each fortigate needs a non-empty name")
        if not isinstance(host, str) or not host.strip():
            raise RuntimeError(f"FortiGate {name!r} is missing host")

        api_token: Optional[str] = None
        if isinstance(d.get("api_token"), str) and d["api_token"].strip():
            api_token = d["api_token"].strip()
        elif isinstance(d.get("api_token_file"), str) and d["api_token_file"].strip():
            api_token = _read_secret_file(d["api_token_file"].strip())
        if not api_token:
            raise RuntimeError(f"FortiGate {name!r} is missing api_token/api_token_file")

        verify_ssl = d.get("verify_ssl", True)
        if not isinstance(verify_ssl, bool):
            raise RuntimeError(f"FortiGate {name!r} verify_ssl must be boolean")

        fortigate_devices.append(
            FortiGateDevice(name=name.strip(), host=host.strip(), api_token=api_token, verify_ssl=verify_ssl)
        )

    return Settings(
        fortigate_devices=fortigate_devices,
        netbox_url=netbox_url,
        netbox_api_token=nb_token,
        netbox_timeout=netbox_timeout,
        sync_data_dir=sync_data_dir,
        cache_dir=cache_dir,
        use_cached_data=use_cached_data,
        vlan_translations=vlan_translations,
        log_level=log_level,
        test_switch=test_switch.strip() if isinstance(test_switch, str) and test_switch.strip() else None,
    )


def load_settings() -> Settings:
    """Load settings from environment variables and JSON device file (legacy) or YAML (new)."""


    # YAML-first mode (single source of truth)
    app_config_file = os.getenv("APP_CONFIG_FILE")
    if app_config_file:
        return _load_settings_from_yaml(app_config_file)

    # Legacy mode (env + devices JSON file)
    devices_file = os.getenv("FG_DEVICES_FILE", "fortigate_devices.json")
    try:
        with open(devices_file, "r", encoding="utf-8") as f:
            devices_raw = json.load(f)
    except FileNotFoundError as exc:
        raise RuntimeError(f"FortiGate devices file not found: {devices_file}") from exc

    fortigate_devices: List[FortiGateDevice] = []
    for d in devices_raw:
        name = d["name"]
        host = d["host"]

        token_file = d.get("token_file")
        api_token = _read_secret_file(token_file) if token_file else d.get("api_token")
        if not api_token:
            raise RuntimeError(f"FortiGate device '{name}' is missing api_token/token_file.")

        fortigate_devices.append(
            FortiGateDevice(
                name=name,
                host=host,
                api_token=api_token,
                verify_ssl=d.get("verify_ssl", True),
            )
        )

    netbox_url = os.getenv("NETBOX_URL")
    if not netbox_url:
        raise RuntimeError(
            "NETBOX_URL not set. Please check your env.production file or environment variables. "
            "Ensure the file has no leading/trailing spaces and uses the format: NETBOX_URL=https://netbox.example.com"
        )
    netbox_url = _normalize_netbox_url(netbox_url)

    # Prioritize direct env var over file-based token
    nb_token = os.getenv("NETBOX_API_TOKEN")
    if not nb_token:
        # Fall back to file-based token if direct env var not set
        nb_token_file = os.getenv("NETBOX_API_TOKEN_FILE", "secrets/netbox_api_token")
        nb_token = _read_secret_file(nb_token_file)
    if not nb_token:
        raise RuntimeError(
            "NetBox API token not configured. Set NETBOX_API_TOKEN or "
            "NETBOX_API_TOKEN_FILE (default: secrets/netbox_api_token)."
        )

    log_level = os.getenv("LOG_LEVEL", "INFO")

    sync_data_dir = Path(os.getenv("SYNC_DATA_DIR", "/app/data"))
    sync_data_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = Path(os.getenv("CACHE_DIR", "/app/data/cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)

    use_cached_data = _env_bool("USE_CACHED_DATA", default=False)

    try:
        netbox_timeout = int(os.getenv("NETBOX_TIMEOUT", "120"))
    except ValueError as exc:
        raise RuntimeError("NETBOX_TIMEOUT must be an integer (seconds).") from exc

    test_switch = os.getenv("TEST_SWITCH")

    return Settings(
        fortigate_devices=fortigate_devices,
        netbox_url=netbox_url,
        netbox_api_token=nb_token,
        netbox_timeout=netbox_timeout,
        sync_data_dir=sync_data_dir,
        cache_dir=cache_dir,
        use_cached_data=use_cached_data,
        vlan_translations={},
        log_level=log_level,
        test_switch=test_switch,
    )
