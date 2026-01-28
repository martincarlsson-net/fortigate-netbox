import json
import logging
import shutil
from pathlib import Path
from typing import List

from .models import Switch

logger = logging.getLogger(__name__)


def clear_data_dir(data_dir: Path) -> None:
    """
    Remove all files and subdirectories from the data directory.

    This is intended to be run once per sync (e.g. daily) before new
    FortiGate API calls, so only the latest snapshot is kept.
    """
    if not data_dir.exists():
        return

    logger.info("Clearing data directory %s", data_dir)
    for child in data_dir.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)


def save_switches_for_device(data_dir: Path, fortigate_name: str, switches: List[Switch]) -> Path:
    """
    Persist normalized switch data for a single FortiGate to JSON.

    File naming convention: <fortigate_name>_switches.json
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / f"{fortigate_name}_switches.json"
    logger.info("Saving switches for %s to %s", fortigate_name, file_path)

    payload = [
        {
            "name": sw.name,
            "ports": [
                {
                    "name": p.name,
                    "native_vlan": p.native_vlan,
                    "allowed_vlans": p.allowed_vlans,
                }
                for p in sw.ports.values()
            ],
        }
        for sw in switches
    ]

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    return file_path


def load_all_switches(data_dir: Path) -> List[dict]:
    """
    Load all stored switches from JSON files in the data directory.

    Returns a flat list of switch dicts:
        [{"name": "...", "ports": [...]}, ...]
    """
    switches: List[dict] = []
    if not data_dir.exists():
        logger.warning("Data directory %s does not exist when loading switches.", data_dir)
        return switches

    for file_path in data_dir.glob("*_switches.json"):
        logger.info("Loading switches from %s", file_path)
        with open(file_path, "r", encoding="utf-8") as fh:
            try:
                switches.extend(json.load(fh))
            except json.JSONDecodeError as exc:
                logger.error("Failed to parse %s: %s", file_path, exc)

    return switches

