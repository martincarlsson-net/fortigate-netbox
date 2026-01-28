import logging
import os
import sys
from pathlib import Path

from .cache_manager import CacheManager
from .config import load_settings
from .logging_config import configure_logging
from .sync_switches import run_sync

logger = logging.getLogger(__name__)


def main() -> int:
    # Configure logging early so load_settings() warnings/errors are visible.
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))

    settings = load_settings()

    # Initialize cache manager (currently used for cache visibility/logging).
    cache_manager = CacheManager(
        cache_dir=Path(settings.cache_dir),
        use_cache=settings.use_cached_data,
    )

    if settings.use_cached_data:
        cache_files = cache_manager.list_cache_files()
        logger.info("Cache mode enabled. Found %s cache files:", len(cache_files))
        for cf in cache_files:
            logger.info("  - %s: %s KB (modified: %s)", cf["key"], cf["size_kb"], cf["modified"])
    else:
        logger.info("Cache mode disabled. Fresh API calls will be made and cached (if implemented).")

    test_switch = os.getenv("TEST_SWITCH")
    if test_switch:
        # Filtered run: only operate on a single named switch.
        return run_sync(settings, only_switch_name=test_switch)

    # Full run: process all switches on all FortiGates.
    return run_sync(settings)


if __name__ == "__main__":
    sys.exit(main())
