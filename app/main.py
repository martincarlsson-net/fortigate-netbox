import os
import sys
from cache_manager import CacheManager
from .config import load_settings
from .logging_config import configure_logging
from .sync_switches import run_sync
from .test_switch import run_single_switch_test
import logging
logger = logging.getLogger(__name__)

def main() -> int:
    settings = load_settings()
    configure_logging(settings.log_level)
    # Initialize cache manager
    cache_manager = CacheManager(
        cache_dir=Path(settings.cache_dir),
        use_cache=settings.use_cached_data
    )
        
    # Log cache status
    if settings.use_cached_data:
        cache_files = cache_manager.list_cache_files()
        logger.info(f"Cache mode enabled. Found {len(cache_files)} cache files:")
        for cf in cache_files:
            logger.info(f"  - {cf['key']}: {cf['size_kb']} KB (modified: {cf['modified']})")
    else:
        logger.info("Cache mode disabled. Fresh API calls will be made and cached.")
    test_switch = os.getenv("TEST_SWITCH")
    if test_switch:
        # Dry-run mode: only operate on a single named switch and print comparison.
        
        return run_single_switch_test(settings, test_switch)

    # Full run: process all switches on all FortiGates.
    return run_sync(settings)


if __name__ == "__main__":
    sys.exit(main())


