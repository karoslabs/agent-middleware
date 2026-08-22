"""Centralized logging configuration."""

import logging
import sys

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)


def configure_logging(log_level: str = "INFO") -> None:
    """Configure root logging handlers exactly once.

    Safe to call multiple times (e.g. in tests) without duplicating handlers.
    """

    root = logging.getLogger()
    if root.handlers:
        root.setLevel(log_level.upper())
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    root.setLevel(log_level.upper())
    root.addHandler(handler)

    # Quiet down noisy third-party loggers by default.
    logging.getLogger("google.api_core").setLevel(logging.WARNING)
    logging.getLogger("google.auth").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
