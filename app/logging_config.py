import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


def configure_logging(level: str = "INFO", log_dir: Optional[Path] = None) -> None:
    """Configure root logger with console and optional file handlers.
    
    Args:
        level: Log level (INFO, DEBUG, etc.)
        log_dir: If provided, create a timestamped log file in this directory
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
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d__%H_%M_%S")
        log_file = log_dir / f"fg-nb-log_{timestamp}.log"
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        root.info(f"Logging to file: {log_file}")
