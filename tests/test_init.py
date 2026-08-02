"""Tests for setting up and tearing down the config entry."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.victron_ble import async_unload_entry
from custom_components.victron_ble.const import DOMAIN


async def test_unload_survives_a_setup_that_never_ran(hass: HomeAssistant) -> None:
    """Unloading must not raise when hass.data was never populated.

    If setup fails part-way (or is mocked out) hass.data[DOMAIN] does not exist,
    and an unguarded pop turns a failed setup into a KeyError on teardown.
    """
    entry = MockConfigEntry(domain=DOMAIN, data={"key": "0" * 32}, unique_id="AA:BB")
    entry.add_to_hass(hass)

    assert DOMAIN not in hass.data
    assert await async_unload_entry(hass, entry) is True
