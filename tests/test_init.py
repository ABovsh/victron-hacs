"""Tests for setting up and tearing down the config entry."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sensor_state_data import DeviceKey, SensorUpdate, SensorValue

from custom_components.victron_ble import async_unload_entry
from custom_components.victron_ble.const import (
    CONF_THROTTLE_SECONDS,
    DOMAIN,
    UPDATE_THROTTLE_SECONDS,
)

ADDRESS = "C5:75:97:18:0F:AA"
KEY = "0123456789abcdef0123456789abcdef"


def _entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="SmartShunt",
        data={"name": "SmartShunt", "address": ADDRESS, "key": KEY},
        options=options,
        unique_id=ADDRESS,
    )


@pytest.fixture(name="quiet_device")
def quiet_device_fixture():
    """Replace the BLE parser so no real advertisement decoding is needed."""
    with patch(
        "custom_components.victron_ble.VictronBluetoothDeviceData"
    ) as device_data:
        device_data.return_value.update.return_value = SensorUpdate(
            title=None,
            devices={},
            entity_values={
                DeviceKey("voltage"): SensorValue(DeviceKey("voltage"), "Voltage", 12.0)
            },
        )
        yield device_data


async def test_setup_then_unload(
    hass: HomeAssistant, mock_bluetooth: None, quiet_device: MagicMock
) -> None:
    """A configured device loads its platform and tears down cleanly."""
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.entry_id in hass.data[DOMAIN]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_setup_uses_the_configured_throttle(
    hass: HomeAssistant, mock_bluetooth: None, quiet_device: MagicMock
) -> None:
    """The options value must reach the throttle, not just sit in the entry."""
    entry = _entry(**{CONF_THROTTLE_SECONDS: 300})
    entry.add_to_hass(hass)

    with patch(
        "custom_components.victron_ble._make_throttled_update"
    ) as make_throttled:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert make_throttled.call_args.args[1] == 300


async def test_setup_falls_back_to_the_default_throttle(
    hass: HomeAssistant, mock_bluetooth: None, quiet_device: MagicMock
) -> None:
    """An entry with no options must not break — it gets the default window."""
    entry = _entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.victron_ble._make_throttled_update"
    ) as make_throttled:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert make_throttled.call_args.args[1] == UPDATE_THROTTLE_SECONDS


async def test_changing_options_reloads_the_entry(
    hass: HomeAssistant, mock_bluetooth: None, quiet_device: MagicMock
) -> None:
    """A new throttle only takes effect if the entry is rebuilt with it."""
    entry = _entry(**{CONF_THROTTLE_SECONDS: 60})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch(
        "custom_components.victron_ble._make_throttled_update"
    ) as make_throttled:
        hass.config_entries.async_update_entry(
            entry, options={CONF_THROTTLE_SECONDS: 900}
        )
        await hass.async_block_till_done()

    assert make_throttled.call_args.args[1] == 900


async def test_unload_survives_a_setup_that_never_ran(hass: HomeAssistant) -> None:
    """Unloading must not raise when hass.data was never populated.

    If setup fails part-way (or is mocked out) hass.data[DOMAIN] does not exist,
    and an unguarded pop turns a failed setup into a KeyError on teardown.
    """
    entry = _entry()
    entry.add_to_hass(hass)

    assert DOMAIN not in hass.data
    assert await async_unload_entry(hass, entry) is True


async def test_advertisement_becomes_a_rounded_entity_state(
    hass: HomeAssistant, mock_bluetooth: None
) -> None:
    """End to end: a parsed advertisement must land as a rounded HA state.

    This is the whole point of the fork — the parser output goes through the
    throttle, the description lookup and the native-value rounding before the
    recorder ever sees it. Driving the coordinator's advertisement callback is
    the only way to exercise that chain in one piece.
    """
    from homeassistant.components.bluetooth import BluetoothChange
    from sensor_state_data import SensorDescription, SensorDeviceInfo
    from sensor_state_data.units import Units

    from tests.test_config_flow import SERVICE_INFO

    voltage = DeviceKey("voltage")
    update = SensorUpdate(
        title="SmartShunt",
        devices={
            None: SensorDeviceInfo(
                name="SmartShunt",
                model="SmartShunt 500A",
                manufacturer="Victron",
                sw_version=None,
                hw_version=None,
            )
        },
        entity_descriptions={
            voltage: SensorDescription(
                device_key=voltage,
                native_unit_of_measurement=Units.ELECTRIC_POTENTIAL_VOLT,
            )
        },
        # 52.7719 V must be stored as 52.8: the recorder writes a row per state
        # change, so the trailing jitter digits are what create the rows.
        entity_values={voltage: SensorValue(voltage, "Voltage", 52.7719)},
    )

    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.victron_ble.VictronBluetoothDeviceData"
    ) as device_data:
        device_data.return_value.update.return_value = update
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator._async_handle_bluetooth_event(
            SERVICE_INFO, BluetoothChange.ADVERTISEMENT
        )
        await hass.async_block_till_done()

    states = [s for s in hass.states.async_all("sensor") if "voltage" in s.entity_id]
    assert states, "no voltage entity was created from the advertisement"
    assert states[0].state == "52.8"
