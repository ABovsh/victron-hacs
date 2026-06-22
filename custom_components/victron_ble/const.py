"""Constants for the victron_ble integration."""

DOMAIN = "victron_ble"

# Minimum interval between state updates forwarded to HA recorder.
# The SmartShunt (and other Victron BLE devices) advertise at ~1 Hz;
# throttling to 60 s cuts recorder writes by ~98 % with no loss of
# analytical value.
UPDATE_THROTTLE_SECONDS = 60
