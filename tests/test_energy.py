"""Tests for locally accumulated battery energy totals."""

import math

import pytest

from custom_components.victron_ble.energy import EnergyAccumulator


def test_starts_at_zero_and_serializes_only_totals():
    accumulator = EnergyAccumulator()

    assert accumulator.charged_kwh == 0.0
    assert accumulator.discharged_kwh == 0.0
    assert accumulator.as_dict() == {"charged_kwh": 0.0, "discharged_kwh": 0.0}


def test_integrates_the_previous_power_sample_on_each_valid_interval():
    accumulator = EnergyAccumulator()

    accumulator.update(3600.0, 10.0)
    accumulator.update(3600.0, 11.0)
    accumulator.update(-1800.0, 13.0)

    assert accumulator.charged_kwh == pytest.approx(0.003)
    assert accumulator.discharged_kwh == 0


@pytest.mark.parametrize("gap", [0.0, -1.0, 10.001])
def test_nonpositive_or_stale_interval_is_discarded_but_reanchors(gap):
    accumulator = EnergyAccumulator()

    accumulator.update(3600.0, 10.0)
    accumulator.update(-3600.0, 10.0 + gap)
    accumulator.update(-3600.0, 11.0 + gap)

    assert accumulator.charged_kwh == 0.0
    assert accumulator.discharged_kwh == pytest.approx(0.001)


@pytest.mark.parametrize("invalid", [None, math.nan, math.inf, -math.inf, True])
def test_invalid_power_resets_anchor_and_is_never_integrated(invalid):
    accumulator = EnergyAccumulator()

    accumulator.update(3600.0, 10.0)
    accumulator.update(invalid, 11.0)
    accumulator.update(3600.0, 12.0)
    accumulator.update(3600.0, 13.0)

    assert accumulator.charged_kwh == pytest.approx(0.001)


@pytest.mark.parametrize("invalid_now", [math.nan, math.inf, -math.inf])
def test_nonfinite_timestamp_resets_anchor(invalid_now):
    accumulator = EnergyAccumulator()

    accumulator.update(3600.0, 10.0)
    accumulator.update(3600.0, invalid_now)
    accumulator.update(3600.0, 12.0)
    accumulator.update(3600.0, 13.0)

    assert accumulator.charged_kwh == pytest.approx(0.001)


def test_zero_power_is_a_valid_anchor():
    accumulator = EnergyAccumulator()

    accumulator.update(0.0, 10.0)
    accumulator.update(3600.0, 11.0)

    assert accumulator.charged_kwh == 0.0
    accumulator.update(3600.0, 12.0)
    assert accumulator.charged_kwh == pytest.approx(0.001)


def test_restore_accepts_valid_totals_and_never_integrates_across_restart():
    accumulator = EnergyAccumulator()
    accumulator.restore({"charged_kwh": 2.5, "discharged_kwh": 1})

    accumulator.update(3600.0, 100.0)
    accumulator.update(3600.0, 101.0)

    assert accumulator.as_dict() == {
        "charged_kwh": pytest.approx(2.501),
        "discharged_kwh": 1.0,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"charged_kwh": 1.0},
        {"charged_kwh": -1.0, "discharged_kwh": 1.0},
        {"charged_kwh": math.nan, "discharged_kwh": 1.0},
        {"charged_kwh": math.inf, "discharged_kwh": 1.0},
        {"charged_kwh": True, "discharged_kwh": 1.0},
        {"charged_kwh": 1.0, "discharged_kwh": False},
        {"charged_kwh": "1", "discharged_kwh": 1.0},
    ],
)
def test_restore_ignores_invalid_payloads(payload):
    accumulator = EnergyAccumulator()
    accumulator.update(3600.0, 10.0)

    accumulator.restore(payload)
    accumulator.update(3600.0, 11.0)

    assert accumulator.as_dict() == {"charged_kwh": 0.0, "discharged_kwh": 0.0}
