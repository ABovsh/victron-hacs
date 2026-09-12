"""Integrate observed battery power without extrapolating outages."""

import math


def _finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


class EnergyAccumulator:
    """Separate lifetime charge/discharge totals in kWh."""

    def __init__(self):
        self.charged_kwh = 0.0
        self.discharged_kwh = 0.0
        self._sample = None

    def update(self, power, now):
        if not _finite(power) or not _finite(now):
            self._sample = None
            return
        if self._sample is not None:
            previous_power, previous_time = self._sample
            elapsed = now - previous_time
            if 0 < elapsed <= 10:
                energy = previous_power * elapsed / 3_600_000
                self.charged_kwh += max(energy, 0)
                self.discharged_kwh += max(-energy, 0)
        self._sample = power, now

    def as_dict(self):
        return {"charged_kwh": self.charged_kwh, "discharged_kwh": self.discharged_kwh}

    def restore(self, payload):
        self._sample = None
        if not isinstance(payload, dict):
            return
        values = [payload.get(key) for key in self.as_dict()]
        if all(_finite(value) and value >= 0 for value in values):
            self.charged_kwh, self.discharged_kwh = values
