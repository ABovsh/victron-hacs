"""Tests for the BLE update throttle in __init__.py."""
import time

import pytest
from sensor_state_data import DeviceKey, SensorUpdate, SensorValue

from custom_components.victron_ble import _make_throttled_update

THROTTLE = 60


def _su(**values) -> SensorUpdate:
    """Build a SensorUpdate carrying the given key -> native_value pairs."""
    return SensorUpdate(
        title=None,
        devices={},
        entity_values={
            DeviceKey(key): SensorValue(DeviceKey(key), key, value)
            for key, value in values.items()
        },
    )


def _is_empty(update: SensorUpdate) -> bool:
    return update.entity_values == {}


@pytest.fixture(name="clock")
def clock_fixture(monkeypatch):
    """Freeze time.monotonic and let tests advance it explicitly."""
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    return now


def test_first_update_is_always_forwarded(clock):
    """Entities only register if the very first advertisement gets through."""
    throttled = _make_throttled_update(lambda: _su(voltage=12.0), THROTTLE)
    assert not _is_empty(throttled())


def test_numeric_only_change_is_suppressed_within_window(clock):
    """Jittery telemetry must not reach the recorder on every advertisement."""
    values = {"voltage": 12.0}
    throttled = _make_throttled_update(lambda: _su(**values), THROTTLE)
    throttled()

    clock[0] += 1
    values["voltage"] = 12.1
    assert _is_empty(throttled())


def test_state_change_bypasses_the_window(clock):
    """An alarm that raises inside the window must reach HA immediately."""
    values = {"voltage": 12.0, "alarm_reason": "none"}
    throttled = _make_throttled_update(lambda: _su(**values), THROTTLE)
    throttled()

    clock[0] += 1
    values["alarm_reason"] = "low_voltage"
    result = throttled()
    assert not _is_empty(result)
    assert result.entity_values[DeviceKey("alarm_reason")].native_value == "low_voltage"


def test_state_change_restarts_the_window(clock):
    """A bypass counts as a send, so numeric churn right after stays suppressed."""
    values = {"voltage": 12.0, "alarm_reason": "none"}
    throttled = _make_throttled_update(lambda: _su(**values), THROTTLE)
    throttled()

    clock[0] += 1
    values["alarm_reason"] = "low_voltage"
    throttled()

    clock[0] += 1
    values["voltage"] = 12.5
    assert _is_empty(throttled())


def test_unchanged_state_does_not_bypass(clock):
    """Only actual transitions bypass — a repeated enum value is not an event."""
    values = {"voltage": 12.0, "alarm_reason": "low_voltage"}
    throttled = _make_throttled_update(lambda: _su(**values), THROTTLE)
    throttled()

    clock[0] += 1
    values["voltage"] = 12.1
    assert _is_empty(throttled())


def test_forwarded_again_after_window_elapses(clock):
    """Numeric telemetry still gets through once per throttle window."""
    values = {"voltage": 12.0}
    throttled = _make_throttled_update(lambda: _su(**values), THROTTLE)
    throttled()

    clock[0] += THROTTLE
    values["voltage"] = 12.1
    assert not _is_empty(throttled())


def test_throttle_seconds_is_honoured(clock):
    """The window length comes from the caller, not a hardcoded constant."""
    throttled = _make_throttled_update(lambda: _su(voltage=12.0), 300)
    throttled()

    clock[0] += 60
    assert _is_empty(throttled())
    clock[0] += 240
    assert not _is_empty(throttled())


def test_raw_update_runs_on_every_advertisement(clock):
    """Suppressing the write must not stop the device data from staying fresh."""
    calls = []

    def raw():
        calls.append(1)
        return _su(voltage=12.0)

    throttled = _make_throttled_update(raw, THROTTLE)
    for _ in range(5):
        throttled()
    assert len(calls) == 5
