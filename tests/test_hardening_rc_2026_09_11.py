"""Regression tests through the parser and publication boundaries."""

from unittest.mock import patch

from sensor_state_data import DeviceKey, SensorLibrary
from victron_ble.exceptions import AdvertisementKeyMismatchError

from custom_components.victron_ble import _make_throttled_update
from custom_components.victron_ble.config_flow import ConfigFlow
from custom_components.victron_ble.device import VictronBluetoothDeviceData
from tests.test_config_flow import KEY, SERVICE_INFO
from tests.test_throttle import _su


def test_key_error_survives_parser_guard():
    flow = ConfigFlow()
    flow.hass = None
    with patch(
        "custom_components.victron_ble.config_flow.async_last_service_info",
        return_value=SERVICE_INFO,
    ), patch.object(
        VictronBluetoothDeviceData,
        "_process_mfr_data",
        side_effect=AdvertisementKeyMismatchError("wrong key"),
    ):
        assert not flow._check_key_against_live_advertisement("test", KEY)


def test_failed_frame_does_not_republish_old_or_partial_values():
    data = VictronBluetoothDeviceData(KEY)

    def good(*args):
        data.update_predefined_sensor(
            SensorLibrary.VOLTAGE__ELECTRIC_POTENTIAL_VOLT, 53
        )

    with patch.object(data, "_process_mfr_data", side_effect=good):
        data.update(SERVICE_INFO)

    def bad(*args):
        data.update_predefined_sensor(
            SensorLibrary.VOLTAGE__ELECTRIC_POTENTIAL_VOLT, 99
        )
        raise ValueError("incomplete frame")

    with patch.object(data, "_process_mfr_data", side_effect=bad):
        assert not data.update(SERVICE_INFO).entity_values
    assert data.consecutive_failures == 1
    assert data.last_success_monotonic is not None


def test_alarm_does_not_bypass_energy_cadence():
    now = [1000.0]
    values = {"consumed_energy": 100, "alarm_reason": "no_alarm"}
    with patch(
        "custom_components.victron_ble.time.monotonic", side_effect=lambda: now[0]
    ):
        update = _make_throttled_update(lambda: _su(**values), 60)
        assert DeviceKey("consumed_energy") in update().entity_values
        now[0] += 60
        values.update(consumed_energy=101, alarm_reason="low_voltage")
        result = update()
        assert DeviceKey("alarm_reason") in result.entity_values
        assert DeviceKey("consumed_energy") not in result.entity_values
        now[0] += 240
        assert update().entity_values[DeviceKey("consumed_energy")].native_value == 101


def test_estimates_have_no_long_term_statistics():
    from sensor_state_data.units import Units

    from custom_components.victron_ble.device import VictronSensor
    from custom_components.victron_ble.sensor import SENSOR_DESCRIPTIONS

    for key, unit in (
        (VictronSensor.CONSUMED_ENERGY, Units.ENERGY_WATT_HOUR),
        (VictronSensor.TIME_REMAINING, Units.TIME_MINUTES),
        (VictronSensor.REMAINING_MINS, Units.TIME_MINUTES),
    ):
        assert SENSOR_DESCRIPTIONS[key, unit].state_class is None


async def test_freshness_expires_and_recovers_with_real_parser(hass, mock_bluetooth):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "bluetooth", {})
    import time
    from unittest.mock import MagicMock

    from homeassistant.components.bluetooth import BluetoothChange

    from custom_components.victron_ble import VictronCoordinator

    data = VictronBluetoothDeviceData(KEY)
    coordinator = VictronCoordinator(hass, SERVICE_INFO.address, data, 60)
    processor = MagicMock()
    coordinator._processors.append(processor)

    def good(*args):
        data.update_predefined_sensor(
            SensorLibrary.VOLTAGE__ELECTRIC_POTENTIAL_VOLT, 53
        )

    with patch.object(data, "_process_mfr_data", side_effect=good):
        coordinator._async_handle_bluetooth_event(
            SERVICE_INFO, BluetoothChange.ADVERTISEMENT
        )
    assert coordinator.available
    data.last_success_monotonic = time.monotonic() - 121
    with patch.object(data, "_process_mfr_data", side_effect=ValueError("bad frame")):
        coordinator._async_handle_bluetooth_event(
            SERVICE_INFO, BluetoothChange.ADVERTISEMENT
        )
    coordinator.check_freshness()
    assert not coordinator.available
    assert processor.async_handle_unavailable.called
    with patch.object(data, "_process_mfr_data", side_effect=good):
        coordinator._async_handle_bluetooth_event(
            SERVICE_INFO, BluetoothChange.ADVERTISEMENT
        )
    assert coordinator.available
    assert processor.async_handle_update.call_args.args[0].entity_values


def test_energy_new_counters_have_kwh_precision():
    from sensor_state_data.units import Units

    from custom_components.victron_ble.sensor import (
        SENSOR_DESCRIPTIONS,
        _round_native_value,
    )

    for key in ("charged_kwh", "discharged_kwh"):
        description = SENSOR_DESCRIPTIONS[key, Units.ENERGY_KILO_WATT_HOUR]
        assert _round_native_value(description, 0.1234) == 0.123


def _packet(current=10000, voltage=5200, key=KEY):
    """Synthetic encrypted SmartShunt frame using protocol bit widths."""
    import struct
    from types import SimpleNamespace

    from Crypto.Cipher import AES
    from Crypto.Util import Counter

    fields = [
        (65535, 16),
        (voltage, 16),
        (0, 16),
        (0, 16),
        (3, 2),
        (current & ((1 << 22) - 1), 22),
        (1000, 20),
        (900, 10),
    ]
    bits = offset = 0
    for value, width in fields:
        bits |= value << offset
        offset += width
    cipher = AES.new(
        bytes.fromhex(key),
        AES.MODE_CTR,
        counter=Counter.new(128, initial_value=1, little_endian=True),
    )
    payload = struct.pack("<HHBH", 0x10, 0xA389, 2, 1)
    payload += bytes.fromhex(key)[:1] + cipher.encrypt(bits.to_bytes(15, "little"))
    return SimpleNamespace(
        manufacturer_data={737: payload},
        service_uuids=[],
        name="Test Shunt",
        address="AA:BB:CC:DD:EE:FF",
        rssi=-60,
    )


def test_encrypted_frames_accumulate_before_throttle_and_accept_missing_voltage():
    import pytest

    data = VictronBluetoothDeviceData(KEY)
    with patch("custom_components.victron_ble.device.time.monotonic", return_value=100):
        first = data.update(_packet())
    assert first.entity_values[DeviceKey("voltage")].native_value == 52
    with patch("custom_components.victron_ble.device.time.monotonic", return_value=101):
        result = data.update(_packet())
    assert data.energy.charged_kwh == pytest.approx(520 / 3600000)
    assert result.entity_values[DeviceKey("charged_kwh")].native_value == pytest.approx(
        0.000144
    )
    missing = data.update(_packet(voltage=32767))
    assert missing.entity_values[DeviceKey("output_power")].native_value is None
    assert missing.entity_values[DeviceKey("consumed_energy")].native_value is None


def test_wrong_key_real_encrypted_packet():
    flow = ConfigFlow()
    flow.hass = None
    with patch(
        "custom_components.victron_ble.config_flow.async_last_service_info",
        return_value=_packet(),
    ):
        assert not flow._check_key_against_live_advertisement("test", "ff" * 16)


async def test_energy_checkpoint_restored_after_reload(hass, mock_bluetooth):
    from custom_components.victron_ble.const import DOMAIN
    from tests.test_init import _entry

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.device_data.energy.restore(
        {"charged_kwh": 1.234, "discharged_kwh": 2.345}
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    restored = hass.data[DOMAIN][entry.entry_id].device_data.energy
    assert restored.as_dict() == {"charged_kwh": 1.234, "discharged_kwh": 2.345}
