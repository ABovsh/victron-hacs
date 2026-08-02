"""Tests for the advertisement parser wrapper.

These cover the failure modes reported repeatedly against the upstream
project: a single unparseable advertisement taking the whole device down, and
a zero reading being discarded because it is falsy.
"""

import logging
from unittest.mock import patch

import pytest

from custom_components.victron_ble.device import (
    _WARNED_PARSE_FAILURES,
    VictronBluetoothDeviceData,
)
from tests.test_config_flow import KEY, SERVICE_INFO


@pytest.fixture(autouse=True)
def reset_warned():
    """The warn-once set is module state — do not leak it between tests."""
    _WARNED_PARSE_FAILURES.clear()
    yield
    _WARNED_PARSE_FAILURES.clear()


def test_parse_failure_does_not_propagate():
    """An enum value the library does not know must not kill the update.

    Upstream #209: an Orion XS reporting off_reason 136 raised ValueError out
    of the coordinator's update path 9468 times and the device stopped
    reporting entirely. One bad advertisement is not a broken device.
    """
    data = VictronBluetoothDeviceData(KEY)
    with patch.object(
        VictronBluetoothDeviceData,
        "_process_mfr_data",
        side_effect=ValueError("136 is not a valid OffReason"),
    ):
        data.update(SERVICE_INFO)


def test_parse_failure_is_logged_once_per_device(caplog):
    """Devices advertise at ~1 Hz; one warning per device, not per advert."""
    data = VictronBluetoothDeviceData(KEY)
    with patch.object(
        VictronBluetoothDeviceData,
        "_process_mfr_data",
        side_effect=ValueError("136 is not a valid OffReason"),
    ), caplog.at_level(logging.WARNING):
        data.update(SERVICE_INFO)
        after_first = len(caplog.records)
        for _ in range(5):
            data.update(SERVICE_INFO)

    assert after_first == 1
    assert len(caplog.records) == 1
    assert "136 is not a valid OffReason" in caplog.text


def test_unidentifiable_device_is_logged_once(caplog):
    """Upstream #156: an unsupported model logged an error on every advert."""
    data = VictronBluetoothDeviceData(KEY)
    with patch(
        "custom_components.victron_ble.device.detect_device_type", return_value=None
    ), caplog.at_level(logging.WARNING):
        for _ in range(5):
            data.update(SERVICE_INFO)

    assert len(caplog.records) == 1


def test_a_successful_parse_clears_the_warning_latch():
    """A device that recovers must be able to warn again if it breaks later."""
    data = VictronBluetoothDeviceData(KEY)
    with patch.object(
        VictronBluetoothDeviceData, "_process_mfr_data", side_effect=ValueError("boom")
    ):
        data.update(SERVICE_INFO)
    assert _WARNED_PARSE_FAILURES

    with patch.object(VictronBluetoothDeviceData, "_process_mfr_data"):
        data.update(SERVICE_INFO)

    assert not _WARNED_PARSE_FAILURES


def test_zero_external_load_is_reported_not_dropped():
    """Upstream #140: a load output switched off must read 0, not go stale.

    `if parsed.get_external_device_load():` is falsy for 0 A, so the sensor
    kept its last non-zero reading and eventually went unavailable — which
    silently corrupts any daily-total calculation built on it.
    """
    from unittest.mock import MagicMock

    from victron_ble.devices import SolarChargerData

    from custom_components.victron_ble.device import VictronSensor

    parsed = MagicMock(spec=SolarChargerData)
    parsed._data = {}
    parsed.get_model_name.return_value = "SmartSolar MPPT 100/20"
    parsed.get_charge_state.return_value.name = "FLOAT"
    parsed.get_charger_error.return_value.name = "NO_ERROR"
    parsed.get_battery_voltage.return_value = 52.8
    parsed.get_battery_charging_current.return_value = 0.0
    parsed.get_solar_power.return_value = 0
    parsed.get_yield_today.return_value = 1234
    parsed.get_external_device_load.return_value = 0.0

    recorded = {}
    data = VictronBluetoothDeviceData(KEY)
    with patch(
        "custom_components.victron_ble.device.detect_device_type",
        return_value=lambda key: MagicMock(parse=lambda payload: parsed),
    ), patch.object(
        VictronBluetoothDeviceData,
        "update_sensor",
        side_effect=lambda **kw: recorded.__setitem__(kw["key"], kw),
    ), patch.object(
        VictronBluetoothDeviceData, "update_predefined_sensor"
    ), patch.object(
        VictronBluetoothDeviceData, "set_device_type"
    ):
        data.update(SERVICE_INFO)

    assert recorded[VictronSensor.EXTERNAL_DEVICE_LOAD]["native_value"] == 0.0


def test_solar_yield_is_energy_not_current():
    """A Wh reading declared as device_class CURRENT is simply wrong.

    The solar-charger branch reported yield today in watt-hours while tagging
    it as an electric current, which is a unit/class combination Home
    Assistant rejects.
    """
    from unittest.mock import MagicMock

    from homeassistant.components.sensor import SensorDeviceClass
    from victron_ble.devices import SolarChargerData

    from custom_components.victron_ble.device import VictronSensor

    parsed = MagicMock(spec=SolarChargerData)
    parsed._data = {}
    parsed.get_model_name.return_value = "SmartSolar MPPT 100/20"
    parsed.get_charge_state.return_value.name = "FLOAT"
    parsed.get_charger_error.return_value.name = "NO_ERROR"
    parsed.get_battery_voltage.return_value = 52.8
    parsed.get_battery_charging_current.return_value = 1.0
    parsed.get_solar_power.return_value = 50
    parsed.get_yield_today.return_value = 1234
    parsed.get_external_device_load.return_value = None

    recorded = {}
    data = VictronBluetoothDeviceData(KEY)
    with patch(
        "custom_components.victron_ble.device.detect_device_type",
        return_value=lambda key: MagicMock(parse=lambda payload: parsed),
    ), patch.object(
        VictronBluetoothDeviceData,
        "update_sensor",
        side_effect=lambda **kw: recorded.__setitem__(kw["key"], kw),
    ), patch.object(
        VictronBluetoothDeviceData, "update_predefined_sensor"
    ), patch.object(
        VictronBluetoothDeviceData, "set_device_type"
    ):
        data.update(SERVICE_INFO)

    yield_today = recorded[VictronSensor.YIELD_TODAY]
    assert yield_today["device_class"] is SensorDeviceClass.ENERGY
