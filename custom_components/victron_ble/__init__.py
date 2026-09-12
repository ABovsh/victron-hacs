"""The victron_ble integration."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import timedelta
from typing import Any

from homeassistant.components.bluetooth import BluetoothScanningMode
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothProcessorCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from sensor_state_data import SensorUpdate

from .const import CONF_THROTTLE_SECONDS, DOMAIN, UPDATE_THROTTLE_SECONDS
from .device import VictronBluetoothDeviceData

# How often the lifetime energy counters are checkpointed to .storage.
#
# An unclean shutdown loses whatever accumulated since the last checkpoint, and
# the counters are TOTAL_INCREASING: HA reads a drop of more than 10 % as a
# counter reset and adds the whole restored value to the statistics sum again.
# At a few hundred watts a five-minute window was large enough to trip that on a
# young counter; one minute keeps the lost slice under the tolerance from the
# first minutes of the counter's life.
ENERGY_SAVE_INTERVAL = timedelta(seconds=60)

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
    force: Callable[[], bool] = lambda: False,
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
    slow_sent: dict[Any, float] = {}
    slow_keys = {
        "consumed_energy",
        "charged_kwh",
        "discharged_kwh",
        "time_remaining",
        "remaining_mins",
        "signal_strength",
    }

    def _throttled(*args: Any, **kwargs: Any) -> SensorUpdate:
        recovery = force()
        result = raw_update(*args, **kwargs)
        if not result.entity_values:
            return _empty
        now = time.monotonic()
        states = _state_like_values(result)
        if (
            recovery
            or states != _last_states[0]
            or now - _last_sent[0] >= throttle_seconds
        ):
            _last_sent[0] = now
            _last_states[0] = states
            values = {}
            for key, value in result.entity_values.items():
                if (
                    key.key not in slow_keys
                    or recovery
                    or now - slow_sent.get(key, -100000) >= 300
                ):
                    values[key] = value
                    if key.key in slow_keys:
                        slow_sent[key] = now
            return replace(result, entity_values=values)
        return _empty

    return _throttled


class VictronCoordinator(PassiveBluetoothProcessorCoordinator):
    """Bluetooth reception and successful decoding have separate freshness."""

    saved_energy: dict[str, float]
    save_energy: Callable[..., Awaitable[None]]

    def __init__(self, hass, address, data, throttle):
        self.device_data = data
        self._last_available = False
        super().__init__(
            hass,
            _LOGGER,
            address=address,
            mode=BluetoothScanningMode.ACTIVE,
            update_method=_make_throttled_update(
                data.update, throttle, lambda: not self.available
            ),
        )

    @property
    def available(self):
        last = self.device_data.last_success_monotonic
        return last is not None and time.monotonic() - last < 120 and super().available

    @callback
    def check_freshness(self, _now=None):
        available = self.available
        if available != self._last_available:
            self._last_available = available
            for processor in self._processors:
                processor.async_handle_unavailable()

    @callback
    def _process_update(self, update, was_available=None):
        super()._process_update(update, was_available)
        self.check_freshness()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Victron BLE device from a config entry."""
    address = entry.unique_id
    assert address is not None
    data = VictronBluetoothDeviceData(entry.data["key"])
    throttle_seconds = max(
        60, entry.options.get(CONF_THROTTLE_SECONDS, UPDATE_THROTTLE_SECONDS)
    )
    store: Store[dict[str, float]] = Store(
        hass, 1, f"{DOMAIN}.energy.{entry.entry_id}", atomic_writes=True
    )
    data.energy.restore(await store.async_load() or {})
    coordinator = hass.data.setdefault(DOMAIN, {})[entry.entry_id] = VictronCoordinator(
        hass, address, data, throttle_seconds
    )
    coordinator.saved_energy = data.energy.as_dict()

    async def save_energy(_event=None, *, immediate=False):
        totals = data.energy.as_dict()
        if totals == coordinator.saved_energy:
            return
        coordinator.saved_energy = totals
        if immediate:
            # Teardown: the next setup reads the file back, so it has to be on
            # disk before this coroutine returns or a reload restores stale
            # totals from the previous checkpoint.
            await store.async_save(totals)
            return
        # Steady state: async_delay_save coalesces bursts into one write and
        # registers Store's own final-write listener, so a checkpoint still in
        # flight is flushed if HA stops before the next tick.
        store.async_delay_save(lambda: totals, 0)

    async def save_energy_on_stop(_event):
        await save_energy(immediate=True)

    coordinator.save_energy = save_energy
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    entry.async_on_unload(
        async_track_time_interval(
            hass, coordinator.check_freshness, timedelta(seconds=15)
        )
    )
    entry.async_on_unload(
        async_track_time_interval(hass, save_energy, ENERGY_SAVE_INTERVAL)
    )
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, save_energy_on_stop)
    )
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
        if coordinator := hass.data.get(DOMAIN, {}).get(entry.entry_id):
            await coordinator.save_energy(immediate=True)
        # A setup that failed part-way never stored anything, so tolerate both
        # the domain and the entry being absent rather than raising on teardown.
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    return unload_ok
