"""Utility helper functions."""

from datetime import datetime
from typing import Any


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format datetime to string."""
    if dt is None:
        return ""
    return dt.strftime(format_str)


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to max length."""
    if not text or len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def safe_get(dictionary: dict, *keys: str, default: Any = None) -> Any:
    """Safely get nested dictionary value."""
    result = dictionary
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key)
            if result is None:
                return default
        else:
            return default
    return result