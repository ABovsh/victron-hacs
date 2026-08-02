"""Constants for the victron_ble integration."""

DOMAIN = "victron_ble"

# Default minimum interval between state updates forwarded to HA recorder.
# The SmartShunt (and other Victron BLE devices) advertise at ~1 Hz;
# throttling to 60 s cuts recorder writes by ~98 % with no loss of
# analytical value. State/alarm changes bypass the throttle entirely.
# Overridable per device via the options flow (CONF_THROTTLE_SECONDS).
UPDATE_THROTTLE_SECONDS = 60

CONF_THROTTLE_SECONDS = "throttle_seconds"
