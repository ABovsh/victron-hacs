"""The victron_ble integration."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from homeassistant.components.bluetooth import BluetoothScanningMode
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothProcessorCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from sensor_state_data import SensorUpdate

from .const import DOMAIN, UPDATE_THROTTLE_SECONDS
from .device import VictronBluetoothDeviceData

PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


def _make_throttled_update(
    raw_update: Callable[..., SensorUpdate],
) -> Callable[..., SensorUpdate]:
    """Wrap *raw_update* so HA receives a real update at most once per UPDATE_THROTTLE_SECONDS.

    Every BLE advertisement is still parsed (raw_update is called every time)
    so the underlying data object stays current.  Between throttle windows the
    wrapper returns an empty SensorUpdate so the passive-processor coordinator
    writes no states to the recorder.

    The very first advertisement is always forwarded so that entities are
    registered immediately on startup.
    """
    _empty = SensorUpdate(
        title=None,
        devices={},
        entity_descriptions={},
        entity_values={},
        binary_entity_descriptions={},
        binary_entity_values={},
        events={},
    )
    # Sentinel: never fired yet.
    _last_sent: list[float] = [-UPDATE_THROTTLE_SECONDS - 1.0]

    def _throttled(*args: Any, **kwargs: Any) -> SensorUpdate:
        result = raw_update(*args, **kwargs)
        now = time.monotonic()
        if now - _last_sent[0] >= UPDATE_THROTTLE_SECONDS:
            _last_sent[0] = now
            return result
        return _empty

    return _throttled


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Victron BLE device from a config entry."""
    address = entry.unique_id
    assert address is not None
    data = VictronBluetoothDeviceData(entry.data["key"])
    coordinator = hass.data.setdefault(DOMAIN, {})[entry.entry_id] = (
        PassiveBluetoothProcessorCoordinator(
            hass,
            _LOGGER,
            address=address,
            mode=BluetoothScanningMode.ACTIVE,
            update_method=_make_throttled_update(data.update),
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(
        coordinator.async_start()
    )  # only start after all platforms have had a chance to subscribe
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
