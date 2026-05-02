"""Shared timestamp helpers for session and runtime logging."""

from datetime import datetime, timezone


TIMESTAMP_FORMAT = "%m-%d-%Y %H:%M:%S.%f"
FILENAME_TIMESTAMP_FORMAT = "%m-%d-%Y_%H-%M-%S-%f"


def now_timestamp() -> str:
    """Return a UTC timestamp with millisecond precision."""
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)[:-3]


def now_filename_timestamp() -> str:
    """Return a filename-safe UTC timestamp with millisecond precision."""
    return datetime.now(timezone.utc).strftime(FILENAME_TIMESTAMP_FORMAT)[:-3]
