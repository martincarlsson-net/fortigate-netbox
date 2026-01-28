import os
import sys

from .config import load_settings
from .logging_config import configure_logging
from .sync_switches import run_sync
from .test_switch import run_single_switch_test


def main() -> int:
    settings = load_settings()
    configure_logging(settings.log_level)

    test_switch = os.getenv("TEST_SWITCH")
    if test_switch:
        # Dry-run mode: only operate on a single named switch and print comparison.
        return run_single_switch_test(settings, test_switch)

    # Full run: process all switches on all FortiGates.
    return run_sync(settings)


if __name__ == "__main__":
    sys.exit(main())


