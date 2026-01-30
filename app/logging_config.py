import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def configure_logging(level: str = "INFO", log_dir: Optional[Path] = None) -> None:
    """Configure root logger with console and optional file handlers.

    Args:
        level: Log level (INFO, DEBUG, etc.)
        log_dir: If provided, create a timestamped log file in this directory.
    """
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    # Console handler (always present)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # File handler (optional)
    if log_dir:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d__%H_%M_%S")
            log_file = log_dir / f"fg-nb-log_{timestamp}.log"
            file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
            root.info("Logging to file: %s", log_file)
        except PermissionError as exc:
            root.error(
                "File logging disabled (permission error writing to %s). "
                "If you mounted a host directory, ensure it is writable for the container user (uid=%s gid=%s). "
                "Error: %s",
                str(log_dir),
                os.getuid(),
                os.getgid(),
                exc,
            )
        except OSError as exc:
            root.error(
                "File logging disabled (OS error creating log file under %s): %s",
                str(log_dir),
                exc,
            )
