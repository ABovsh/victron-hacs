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

from .const import CONF_THROTTLE_SECONDS, DOMAIN, UPDATE_THROTTLE_SECONDS
from .device import VictronBluetoothDeviceData

PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


def _state_like_values(update: SensorUpdate) -> dict[Any, Any]:
    """Return the entity values that describe a state rather than a measurement.

    Alarm reasons, charger errors, operation modes and off reasons are events:
    they have to reach Home Assistant the moment they change, not whenever the
    throttle window happens to expire.  bool counts as state-like even though it
    is an int subclass — an on/off flag is a transition, not telemetry.
    """
    return {
        device_key: value.native_value
        for device_key, value in update.entity_values.items()
        if isinstance(value.native_value, bool)
        or not isinstance(value.native_value, (int, float))
    }


def _make_throttled_update(
    raw_update: Callable[..., SensorUpdate],
    throttle_seconds: float,
) -> Callable[..., SensorUpdate]:
    """Wrap *raw_update* so HA receives a real update at most once per window.

    Every BLE advertisement is still parsed (raw_update is called every time) so
    the underlying data object stays current.  Between throttle windows the
    wrapper returns an empty SensorUpdate so the passive-processor coordinator
    writes no states to the recorder.

    Two things always get through: the very first advertisement, so that
    entities are registered immediately on startup, and any advertisement in
    which a state-like value changed (see _state_like_values), so that an alarm
    raised and cleared inside one window is never lost.  A bypass counts as a
    send and restarts the window.
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
    _last_sent: list[float] = [-throttle_seconds - 1.0]
    # None (not {}) so the first advertisement always looks like a change.
    _last_states: list[dict[Any, Any] | None] = [None]

    def _throttled(*args: Any, **kwargs: Any) -> SensorUpdate:
        result = raw_update(*args, **kwargs)
        now = time.monotonic()
        states = _state_like_values(result)
        if states != _last_states[0] or now - _last_sent[0] >= throttle_seconds:
            _last_sent[0] = now
            _last_states[0] = states
            return result
        return _empty

    return _throttled


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Victron BLE device from a config entry."""
    address = entry.unique_id
    assert address is not None
    data = VictronBluetoothDeviceData(entry.data["key"])
    throttle_seconds = entry.options.get(CONF_THROTTLE_SECONDS, UPDATE_THROTTLE_SECONDS)
    coordinator = hass.data.setdefault(DOMAIN, {})[entry.entry_id] = (
        PassiveBluetoothProcessorCoordinator(
            hass,
            _LOGGER,
            address=address,
            mode=BluetoothScanningMode.ACTIVE,
            update_method=_make_throttled_update(data.update, throttle_seconds),
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    entry.async_on_unload(
        coordinator.async_start()
    )  # only start after all platforms have had a chance to subscribe
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # A setup that failed part-way never stored anything, so tolerate both
        # the domain and the entry being absent rather than raising on teardown.
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    return unload_ok
