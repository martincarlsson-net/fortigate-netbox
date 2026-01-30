import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml


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
    max_netbox_updates: int = 1


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
    netbox_url = netbox_url.strip()

    netbox_timeout = netbox.get("timeout", 120)
    try:
        netbox_timeout = int(netbox_timeout)
    except Exception as exc:
        raise RuntimeError("netbox.timeout must be an integer (seconds)") from exc

    nb_token = netbox.get("api_token")
    if not isinstance(nb_token, str) or not nb_token.strip():
        raise RuntimeError("netbox.api_token is required")
    nb_token = nb_token.strip()

    # Runtime config
    runtime = raw.get("runtime") or {}
    if not isinstance(runtime, dict):
        raise RuntimeError("runtime must be a mapping/object")

    log_level = str(runtime.get("log_level", "INFO"))
    test_switch = runtime.get("test_switch")
    if test_switch is not None and not isinstance(test_switch, str):
        raise RuntimeError("runtime.test_switch must be a string or null")

    max_netbox_updates_raw = runtime.get("max_netbox_updates", 1)
    try:
        max_netbox_updates = int(max_netbox_updates_raw)
    except Exception as exc:
        raise RuntimeError("runtime.max_netbox_updates must be an integer") from exc
    if max_netbox_updates < 0:
        raise RuntimeError("runtime.max_netbox_updates must be >= 0")

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

        api_token = d.get("api_token")
        if not isinstance(api_token, str) or not api_token.strip():
            raise RuntimeError(f"FortiGate {name!r} is missing api_token")

        verify_ssl = d.get("verify_ssl", True)
        if not isinstance(verify_ssl, bool):
            raise RuntimeError(f"FortiGate {name!r} verify_ssl must be boolean")

        fortigate_devices.append(
            FortiGateDevice(name=name.strip(), host=host.strip(), api_token=api_token.strip(), verify_ssl=verify_ssl)
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
        max_netbox_updates=max_netbox_updates,
    )


def load_settings() -> Settings:
    """Load settings from YAML config file or legacy env+JSON mode."""

    # YAML-first mode (single source of truth)
    app_config_file = os.getenv("APP_CONFIG_FILE")
    if app_config_file:
        return _load_settings_from_yaml(app_config_file)

    # Legacy mode not supported - raise clear error
    raise RuntimeError(
        "APP_CONFIG_FILE environment variable is required. "
        "Please create a config.yml file and set APP_CONFIG_FILE=/app/config.yml. "
        "See config.example.yml for template."
    )
