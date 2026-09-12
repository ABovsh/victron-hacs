"""Tests for the deliberately minimal Victron BLE diagnostics download."""

from datetime import UTC, datetime
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.victron_ble.const import DOMAIN
from custom_components.victron_ble.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_reports_only_parse_health(
    hass: HomeAssistant, monkeypatch
) -> None:
    """Diagnostics contain useful health data without identifiable BLE data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Anton's SmartShunt",
        unique_id="C5:75:97:18:0F:AA",
        data={
            "key": "0123456789abcdef0123456789abcdef",
            "address": "C5:75:97:18:0F:AA",
        },
    )
    device_data = SimpleNamespace(
        last_success_monotonic=100.25,
        last_success_utc=datetime(2026, 9, 11, 12, 30, tzinfo=UTC),
        consecutive_failures=3,
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(
        available=True, device_data=device_data
    )
    monkeypatch.setattr(
        "custom_components.victron_ble.diagnostics.time.monotonic", lambda: 112.75
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics == {
        "integration_version": "0.1.10",
        "health": {
            "available": True,
            "last_success_utc": "2026-09-11T12:30:00+00:00",
            "last_success_age_seconds": 12.5,
            "consecutive_failures": 3,
        },
    }
    rendered = str(diagnostics)
    for secret in (
        "0123456789abcdef0123456789abcdef",
        "C5:75:97:18:0F:AA",
        "Anton's SmartShunt",
    ):
        assert secret not in rendered


async def test_diagnostics_handles_an_entry_without_runtime_data(
    hass: HomeAssistant,
) -> None:
    """A failed or incomplete setup still produces a safe diagnostics file."""
    entry = MockConfigEntry(domain=DOMAIN)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["health"] == {
        "available": None,
        "last_success_utc": None,
        "last_success_age_seconds": None,
        "consecutive_failures": None,
    }
