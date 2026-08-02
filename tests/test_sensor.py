"""Tests for the victron_ble sensor platform."""

import logging

import pytest
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothEntityKey,
)
from homeassistant.components.sensor import SensorDeviceClass, SensorEntityDescription
from sensor_state_data import DeviceKey, SensorDescription, SensorUpdate, SensorValue
from sensor_state_data.units import Units

from custom_components.victron_ble.device import VictronSensor
from custom_components.victron_ble.sensor import (
    _WARNED_UNKNOWN,
    SENSOR_DESCRIPTIONS,
    _round_native_value,
    sensor_update_to_bluetooth_data_update,
)


@pytest.fixture(autouse=True)
def reset_warned_unknown():
    """The warn-once set is module state — do not leak it between tests."""
    _WARNED_UNKNOWN.clear()
    yield
    _WARNED_UNKNOWN.clear()


KNOWN_KEY = str(SensorDeviceClass.VOLTAGE)
KNOWN_UNIT = Units.ELECTRIC_POTENTIAL_VOLT
BOGUS_KEY = "sensor_key_added_by_a_future_library_release"


def _su(*specs) -> SensorUpdate:
    """Build a SensorUpdate from (key, unit, value) triples."""
    return SensorUpdate(
        title=None,
        devices={},
        entity_descriptions={
            DeviceKey(key): SensorDescription(
                device_key=DeviceKey(key), native_unit_of_measurement=unit
            )
            for key, unit, _ in specs
        },
        entity_values={
            DeviceKey(key): SensorValue(DeviceKey(key), key, value)
            for key, _, value in specs
        },
    )


def test_unknown_sensor_key_is_skipped_not_raised():
    """A key the map does not know must not blow up the coordinator update.

    The device advertises at ~1 Hz, so a raised KeyError here is an exception
    storm that stops the device updating entirely.
    """
    update = sensor_update_to_bluetooth_data_update(
        _su((KNOWN_KEY, KNOWN_UNIT, 12.5), (BOGUS_KEY, KNOWN_UNIT, 1))
    )

    assert PassiveBluetoothEntityKey(KNOWN_KEY, None) in update.entity_descriptions
    assert PassiveBluetoothEntityKey(BOGUS_KEY, None) not in update.entity_descriptions


def test_unknown_sensor_key_leaves_no_orphan_data():
    """Values and names must be filtered alongside the descriptions."""
    update = sensor_update_to_bluetooth_data_update(
        _su((KNOWN_KEY, KNOWN_UNIT, 12.5), (BOGUS_KEY, KNOWN_UNIT, 1))
    )
    bogus = PassiveBluetoothEntityKey(BOGUS_KEY, None)

    assert bogus not in update.entity_data
    assert bogus not in update.entity_names
    assert update.entity_data[PassiveBluetoothEntityKey(KNOWN_KEY, None)] == 12.5


def test_unknown_sensor_key_warns_only_once(caplog):
    """A 1 Hz advertisement stream must not flood the log."""
    update = _su((BOGUS_KEY, KNOWN_UNIT, 1))
    with caplog.at_level(logging.WARNING):
        sensor_update_to_bluetooth_data_update(update)
        first = len(caplog.records)
        sensor_update_to_bluetooth_data_update(update)

    assert first == 1
    assert len(caplog.records) == 1


def test_descriptions_use_their_own_map_key():
    """Guards against copy-paste: AC apparent power once carried the AC current key."""
    for (key, _unit), description in SENSOR_DESCRIPTIONS.items():
        if isinstance(key, VictronSensor):
            assert (
                description.key == key
            ), f"{key} maps to a description for {description.key}"


def test_no_duplicate_map_entries():
    """Byte-identical duplicates silently overwrite each other — keep one of each."""
    import ast
    import pathlib

    source = pathlib.Path("custom_components/victron_ble/sensor.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and len(node.keys) > 20:
            literals = [ast.dump(k) for k in node.keys if k is not None]
            assert len(literals) == len(
                set(literals)
            ), "duplicate SENSOR_DESCRIPTIONS key"
            break
    else:
        raise AssertionError("SENSOR_DESCRIPTIONS literal not found")


def test_round_native_value_by_key():
    """The per-key precision map wins over the device-class fallback."""
    description = SensorEntityDescription(
        key=VictronSensor.CONSUMED_AH,
        device_class=SensorDeviceClass.VOLTAGE,
    )
    assert _round_native_value(description, 12.46) == 12


def test_round_native_value_by_device_class():
    description = SensorEntityDescription(
        key="anything", device_class=SensorDeviceClass.VOLTAGE
    )
    assert _round_native_value(description, 12.46) == 12.5


def test_round_native_value_precision_zero_returns_int():
    description = SensorEntityDescription(
        key="anything", device_class=SensorDeviceClass.POWER
    )
    result = _round_native_value(description, 12.6)
    assert result == 13
    assert isinstance(result, int)


def test_round_native_value_passes_through_unmapped():
    """No precision configured means the value is stored exactly as received."""
    description = SensorEntityDescription(key="anything", device_class=None)
    assert _round_native_value(description, 12.4567) == 12.4567


def test_round_native_value_passes_through_non_numeric():
    description = SensorEntityDescription(
        key="anything", device_class=SensorDeviceClass.VOLTAGE
    )
    assert _round_native_value(description, None) is None
    assert _round_native_value(description, True) is True
    assert _round_native_value(description, "low_voltage") == "low_voltage"
