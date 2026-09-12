"""Recorder round 2026-09-12: deadbands, unit-aware precision, cheap estimate.

Every assertion here traces to a measured finding on Anton's host, recorded in
`03-projects/victron-recorder.md`:

* voltage wrote 325 rows/day while dithering between adjacent 0.1 V steps,
* `consumed_energy` wrote 285 rows/day for `voltage * consumed_ah * -1`, a value
  recomputable from two entities that are already recorded WITH statistics,
* `sensor.nh_smartshunt_power` was excluded from the recorder, which also
  suppressed its statistics and left the energy dashboard's battery `stat_rate`
  reading an empty statistic.
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from sensor_state_data.units import Units

from custom_components.victron_ble import ENERGY_SAVE_INTERVAL
from custom_components.victron_ble.device import (
    VictronBluetoothDeviceData,
    VictronSensor,
)
from custom_components.victron_ble.sensor import (
    SENSOR_DESCRIPTIONS,
    _deadband,
    _round_native_value,
)
from tests.test_config_flow import KEY
from tests.test_hardening_rc_2026_09_11 import _packet

# --- Point 2: the estimate that carries no information of its own -----------


def test_consumed_energy_is_off_by_default():
    """It is voltage * consumed_ah * -1; both inputs are already recorded."""
    description = SENSOR_DESCRIPTIONS[
        VictronSensor.CONSUMED_ENERGY, Units.ENERGY_WATT_HOUR
    ]
    assert description.entity_registry_enabled_default is False


# --- Point 3: deadbands on dithering gauges ---------------------------------


@pytest.mark.parametrize(
    ("device_class", "band"),
    [
        (SensorDeviceClass.VOLTAGE, 0.2),
        (SensorDeviceClass.CURRENT, 0.5),
        (SensorDeviceClass.POWER, 25.0),
    ],
)
def test_measurement_gauges_carry_a_deadband(device_class, band):
    description = SensorEntityDescription(
        key=str(device_class),
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT,
    )
    assert _deadband(description) == band


@pytest.mark.parametrize(
    "state_class",
    [SensorStateClass.TOTAL, SensorStateClass.TOTAL_INCREASING, None],
)
def test_counters_never_get_a_deadband(state_class):
    """Suppressing a counter's publication stalls its statistics sum."""
    description = SensorEntityDescription(
        key="charged_kwh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=state_class,
    )
    assert _deadband(description) is None


def test_soc_is_deliberately_not_deadbanded():
    """State of charge is the most-read number in the system; keep full steps."""
    description = SENSOR_DESCRIPTIONS[SensorDeviceClass.BATTERY, Units.PERCENTAGE]
    assert _deadband(description) is None


# --- Point 6: precision must key on the unit, not the device class alone ----


def test_unmapped_kwh_energy_sensor_is_not_rounded_to_whole_kwh():
    """A blanket ENERGY -> 0 rule silently destroys any future kWh sensor."""
    description = SensorEntityDescription(
        key="some_future_energy_counter",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=Units.ENERGY_KILO_WATT_HOUR,
    )
    assert _round_native_value(description, 1.2345) == 1.234


def test_watt_hour_energy_sensor_still_rounds_to_whole_watt_hours():
    description = SensorEntityDescription(
        key="some_future_wh_counter",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=Units.ENERGY_WATT_HOUR,
    )
    assert _round_native_value(description, 37932.6) == 37933


# --- Point 7: library precision must not be mutated globally ----------------


def test_battery_monitor_frame_does_not_leave_precision_pinned():
    """set_precision is instance state; left at 6 it re-rounds every later frame."""
    data = VictronBluetoothDeviceData(KEY)
    with patch("custom_components.victron_ble.device.time.monotonic", return_value=100):
        data.update(_packet())
    assert data.precision != 6


def test_energy_counters_keep_milli_kwh_resolution_through_the_parser():
    """The library pins precision to 2 mid-update: 0.01 kWh is 10 Wh steps."""
    from sensor_state_data import DeviceKey

    data = VictronBluetoothDeviceData(KEY)
    for tick in (100, 101):
        with patch(
            "custom_components.victron_ble.device.time.monotonic", return_value=tick
        ):
            update = data.update(_packet())
    charged = update.entity_values[DeviceKey("charged_kwh")].native_value
    assert charged == pytest.approx(520 / 3_600_000, abs=5e-7)


# --- Point 4: shrink the energy checkpoint loss window ----------------------


def test_energy_checkpoint_interval_is_one_minute():
    """Five minutes of lost accumulation can exceed HA's 10% reset tolerance."""
    assert ENERGY_SAVE_INTERVAL == timedelta(seconds=60)


async def test_energy_checkpoint_uses_delayed_store_write(hass, mock_bluetooth):
    """async_delay_save coalesces writes and registers Store's final-write flush."""
    from custom_components.victron_ble.const import DOMAIN
    from tests.test_init import _entry

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.device_data.energy.restore({"charged_kwh": 3.5, "discharged_kwh": 4.5})
    with patch("homeassistant.helpers.storage.Store.async_delay_save") as delay_save:
        await coordinator.save_energy()
    assert delay_save.called
    assert delay_save.call_args.args[0]() == {
        "charged_kwh": 3.5,
        "discharged_kwh": 4.5,
    }


# --- Point 5: diagnostics must not hardcode the version ---------------------


async def test_diagnostics_version_follows_the_manifest(hass, mock_bluetooth):
    from custom_components.victron_ble.const import DOMAIN
    from custom_components.victron_ble.diagnostics import (
        async_get_config_entry_diagnostics,
    )
    from tests.test_init import _entry

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    manifest_version = hass.data["custom_components"][DOMAIN].version
    assert diagnostics["integration_version"] == manifest_version


# --- Point 3, behaviour: the deadband must act on the LAST PUBLISHED value ---


def _entity(description, values):
    """A sensor entity wired to a stub processor that yields *values* in turn."""
    from custom_components.victron_ble.sensor import VictronBluetoothSensorEntity

    entity = object.__new__(VictronBluetoothSensorEntity)
    entity.entity_description = description
    entity.entity_key = "k"
    entity.processor = SimpleNamespace(entity_data={"k": None}, available=True)
    entity._written = []
    entity.async_write_ha_state = lambda: entity._written.append(entity.native_value)
    return entity


VOLTAGE = SensorEntityDescription(
    key=str(SensorDeviceClass.VOLTAGE),
    device_class=SensorDeviceClass.VOLTAGE,
    state_class=SensorStateClass.MEASUREMENT,
)


def _feed(entity, *raw):
    for value in raw:
        entity.processor.entity_data["k"] = value
        entity._handle_processor_update(object())
    return entity._written


def test_adjacent_step_dither_is_suppressed():
    """52.6 <-> 52.7 <-> 52.8 wrote 325 rows/day; a 0.2 V band collapses it."""
    entity = _entity(VOLTAGE, None)
    assert _feed(entity, 52.7, 52.6, 52.7, 52.8, 52.7, 52.6) == [52.7]


def test_slow_drift_still_publishes_because_the_band_is_vs_last_published():
    """Comparing against the last raw value would let the sensor stick forever."""
    entity = _entity(VOLTAGE, None)
    written = _feed(entity, 52.0, 52.1, 52.2, 52.3, 52.4, 52.5)
    assert written == [52.0, 52.2, 52.4]
    assert entity._published_value == 52.4


def test_unavailable_clears_the_band_so_recovery_always_publishes():
    entity = _entity(VOLTAGE, None)
    assert _feed(entity, 52.7) == [52.7]
    _feed(entity, 52.75)
    assert entity._written == [52.7], "inside the band, must stay suppressed"

    entity._handle_processor_update(None)
    assert len(entity._written) == 2, "availability path is never deadbanded"
    assert entity._published_value is None

    _feed(entity, 52.75)
    assert len(entity._written) == 3, "band was cleared, first reading publishes"
