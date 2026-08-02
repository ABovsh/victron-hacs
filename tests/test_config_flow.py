"""Test the victron_ble config flow."""

import time
from unittest.mock import patch

import pytest
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from habluetooth import BluetoothServiceInfoBleak
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry
from victron_ble.exceptions import AdvertisementKeyMismatchError

from custom_components.victron_ble.const import CONF_THROTTLE_SECONDS, DOMAIN

ADDRESS = "C5:75:97:18:0F:AA"
KEY = "0123456789abcdef0123456789abcdef"
USER_INPUT = {"name": "test_device", "address": ADDRESS, "key": KEY}

SERVICE_INFO = BluetoothServiceInfoBleak.from_device_and_advertisement_data(
    BLEDevice(ADDRESS, "SmartShunt HQ2242", {}),
    AdvertisementData(
        local_name="SmartShunt HQ2242",
        manufacturer_data={0x02E1: b"\x10" + b"\x00" * 20},
        service_data={},
        service_uuids=[],
        tx_power=-127,
        rssi=-60,
        platform_data=(),
    ),
    "local",
    time.monotonic(),
    True,
)


@pytest.fixture(autouse=True)
def use_mock_bluetooth(mock_bluetooth: None):
    """Keep the bluetooth integration from opening a real HCI socket."""


@pytest.fixture(name="no_advertisement", autouse=True)
def no_advertisement_fixture():
    """Default: the device is not currently in range, so no live key check."""
    with patch(
        "custom_components.victron_ble.config_flow.async_last_service_info",
        return_value=None,
    ) as last_seen:
        yield last_seen


@pytest.fixture(name="skip_setup", autouse=True)
def skip_setup_fixture():
    """Creating an entry must not start a real coordinator."""
    with patch(
        "custom_components.victron_ble.async_setup_entry", return_value=True
    ) as setup:
        yield setup


async def _user_flow(hass: HomeAssistant, user_input: dict) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] is None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()
    return result


async def test_form(hass: HomeAssistant, skip_setup) -> None:
    """The happy path stores the normalised key and creates the entry."""
    result = await _user_flow(hass, USER_INPUT)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "test_device"
    assert result["data"] == USER_INPUT
    assert len(skip_setup.mock_calls) == 1


async def test_key_is_normalised(hass: HomeAssistant) -> None:
    """VictronConnect shows the key spaced and upper-case; users paste it raw."""
    result = await _user_flow(
        hass, {**USER_INPUT, "key": " 0123456789ABCDEF 0123456789abcdef "}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["key"] == KEY


@pytest.mark.parametrize("bad", ["not-hex", "abcd", ""])
async def test_malformed_key_is_rejected(hass: HomeAssistant, bad: str) -> None:
    """A malformed key must stop at the form, not create an entity-less device."""
    result = await _user_flow(hass, {**USER_INPUT, "key": bad})

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"key": "invalid_key"}


async def test_key_contradicted_by_a_live_advertisement_is_rejected(
    hass: HomeAssistant, no_advertisement
) -> None:
    """Victron's key-check byte catches a well-formed but wrong key."""
    no_advertisement.return_value = SERVICE_INFO
    with patch(
        "custom_components.victron_ble.device.VictronBluetoothDeviceData"
    ) as device_data:
        device_data.return_value.update.side_effect = AdvertisementKeyMismatchError(
            "nope"
        )
        result = await _user_flow(hass, USER_INPUT)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"key": "key_mismatch"}


async def test_unrelated_parse_failure_is_not_a_key_verdict(
    hass: HomeAssistant, no_advertisement
) -> None:
    """Only a key mismatch blocks setup; any other parse error must not."""
    no_advertisement.return_value = SERVICE_INFO
    with patch(
        "custom_components.victron_ble.device.VictronBluetoothDeviceData"
    ) as device_data:
        device_data.return_value.update.side_effect = ValueError("truncated frame")
        result = await _user_flow(hass, USER_INPUT)

    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_matching_key_passes_the_live_check(
    hass: HomeAssistant, no_advertisement
) -> None:
    """A key that decrypts the current advertisement is accepted."""
    no_advertisement.return_value = SERVICE_INFO
    with patch("custom_components.victron_ble.device.VictronBluetoothDeviceData"):
        result = await _user_flow(hass, USER_INPUT)

    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_bluetooth_discovery_prefills_the_form(hass: HomeAssistant) -> None:
    """A discovered device should not make the user retype its address."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_BLUETOOTH},
        data=SERVICE_INFO,
    )

    assert result["type"] == FlowResultType.FORM
    defaults = {
        key.schema: key.default()
        for key in result["data_schema"].schema
        if callable(key.default)
    }
    assert defaults["address"] == ADDRESS
    assert defaults["name"] == "SmartShunt HQ2242"


async def test_already_configured_address_aborts(hass: HomeAssistant) -> None:
    """The same shunt must not be addable twice."""
    MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data=USER_INPUT).add_to_hass(hass)

    result = await _user_flow(hass, USER_INPUT)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_replaces_the_key(hass: HomeAssistant) -> None:
    """Re-pairing Instant Readout issues a new key; no need to delete the device."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data=USER_INPUT)
    entry.add_to_hass(hass)
    new_key = "fedcba9876543210fedcba9876543210"

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"key": new_key}
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["key"] == new_key
    assert entry.data["address"] == ADDRESS


async def test_reconfigure_rejects_a_malformed_key(hass: HomeAssistant) -> None:
    """A typo during reconfigure must not silently break a working device."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"key": "oops"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"key": "invalid_key"}
    assert entry.data["key"] == KEY


async def test_options_flow_sets_the_throttle(hass: HomeAssistant) -> None:
    """The throttle window is per device, not a hardcoded constant."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_THROTTLE_SECONDS: 300}
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_THROTTLE_SECONDS] == 300


async def test_options_flow_rejects_an_out_of_range_throttle(
    hass: HomeAssistant,
) -> None:
    """A day-long window would look like a dead device."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData, match="throttle_seconds"):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_THROTTLE_SECONDS: 99999}
        )


async def test_reconfigure_rejects_a_key_the_device_contradicts(
    hass: HomeAssistant, no_advertisement
) -> None:
    """A well-formed but wrong new key must not replace a working one."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data=USER_INPUT)
    entry.add_to_hass(hass)
    no_advertisement.return_value = SERVICE_INFO

    result = await entry.start_reconfigure_flow(hass)
    with patch(
        "custom_components.victron_ble.device.VictronBluetoothDeviceData"
    ) as device_data:
        device_data.return_value.update.side_effect = AdvertisementKeyMismatchError(
            "nope"
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"key": "fedcba9876543210fedcba9876543210"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"key": "key_mismatch"}
    assert entry.data["key"] == KEY
