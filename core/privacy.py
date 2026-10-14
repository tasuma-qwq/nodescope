"""Boundaries between private runtime state and browser-visible data."""
from typing import Any


def public_data(value: Any) -> Any:
    """Copy response data while keeping raw proxy configuration server-side."""
    if isinstance(value, dict):
        return {key: public_data(item) for key, item in value.items()
                if key != "proxy_config"}
    if isinstance(value, list):
        return [public_data(item) for item in value]
    return value
