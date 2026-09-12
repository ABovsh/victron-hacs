"""Redacted diagnostics for Victron BLE config entries."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN


def _isoformat(value: datetime | None) -> str | None:
    """Return a JSON-safe timestamp without exposing device data."""
    return value.isoformat() if value is not None else None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return operational health only, never entry or advertisement data.

    BLE addresses, configured names and encryption keys identify a device or
    grant access to its advertisements.  The diagnostics download therefore
    intentionally contains only the coordinator's aggregate parse health.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    device_data = getattr(coordinator, "device_data", None)
    last_success_monotonic = getattr(device_data, "last_success_monotonic", None)
    age_seconds = (
        max(0.0, time.monotonic() - last_success_monotonic)
        if isinstance(last_success_monotonic, (int, float))
        else None
    )

    # Read from the loaded manifest: a literal here goes stale on the next bump
    # and a diagnostics download that misreports its own version is worse than
    # one that omits it.
    integration = await async_get_integration(hass, DOMAIN)

    return {
        "integration_version": integration.version,
        "health": {
            "available": getattr(coordinator, "available", None),
            "last_success_utc": _isoformat(
                getattr(device_data, "last_success_utc", None)
            ),
            "last_success_age_seconds": age_seconds,
            "consecutive_failures": getattr(device_data, "consecutive_failures", None),
        },
    }
