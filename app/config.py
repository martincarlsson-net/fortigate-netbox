import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

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
    log_level: str = "INFO"


def _read_secret_file(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        logger.warning("Secret file %s does not exist", p)
        return None
    return p.read_text(encoding="utf-8").strip()


def load_settings() -> Settings:
    """Load settings from environment variables and JSON device file."""

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
        raise RuntimeError("NETBOX_URL not set.")
    netbox_url = _normalize_netbox_url(netbox_url)

    nb_token_file = os.getenv("NETBOX_API_TOKEN_FILE", "secrets/netbox_api_token")
    nb_token = _read_secret_file(nb_token_file) or os.getenv("NETBOX_API_TOKEN")
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

    return Settings(
        fortigate_devices=fortigate_devices,
        netbox_url=netbox_url,
        netbox_api_token=nb_token,
        netbox_timeout=netbox_timeout,
        sync_data_dir=sync_data_dir,
        cache_dir=cache_dir,
        use_cached_data=use_cached_data,
        log_level=log_level,
    )
