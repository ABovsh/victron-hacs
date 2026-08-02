# Changelog

All notable changes to this fork are listed here. Versions before 0.1.3 are
upstream [keshavdv/victron-hacs](https://github.com/keshavdv/victron-hacs) and
are not tracked in this file.

## 0.1.7 — 2026-08-02

- `sensor_update_to_bluetooth_data_update()` no longer indexes
  `SENSOR_DESCRIPTIONS` directly. A sensor key present in the `victron_ble`
  library but missing from the map raised `KeyError` inside the coordinator's
  update path; because the devices advertise at ~1 Hz that was an exception on
  every advertisement and the device stopped updating entirely. Unmapped keys
  are now skipped and logged once per distinct (key, unit) pair, and the
  matching entries are filtered out of `entity_data` and `entity_names` so no
  orphan entity is produced.
- State and alarm changes bypass the update throttle. `_make_throttled_update()`
  previously returned an empty `SensorUpdate` for the whole window regardless of
  content, so an `alarm_reason`, `charger_error`, `off_reason`,
  `operation_mode`, `output_state` or similar transition that occurred and
  cleared inside one window never reached Home Assistant. Non-numeric values are
  now compared against the last forwarded update and any change is forwarded
  immediately; a bypass restarts the window. Numeric telemetry is throttled
  exactly as before.
- Throttle interval is configurable per device via a new options flow
  (`throttle_seconds`, default 60, range 0–3600). `UPDATE_THROTTLE_SECONDS` is
  now only the default. Changing it reloads the config entry.
- The advertisement key is validated at setup: it must be 32 hexadecimal
  characters (16 bytes), and when the device is currently advertising the key
  is checked against Victron's key-check byte. Previously any string was
  accepted and produced a configured device with no entities and no error.
- Added a reconfigure flow to change the advertisement key without deleting and
  re-adding the device. VictronConnect issues a new key each time Instant
  Readout is re-paired.
- `(AC_APPARENT_POWER, POWER_VOLT_AMPERE)` mapped to a `SensorEntityDescription`
  carrying `key=AC_CURRENT`. Corrected.
- Removed two byte-identical duplicate `SENSOR_DESCRIPTIONS` entries
  (`(BATTERY, PERCENTAGE)` and `(OUTPUT_CURRENT, ELECTRIC_CURRENT_AMPERE)`).
- `translations/en.json`: the `operation_mode` state list was 3D-printer
  vocabulary (`printing`, `cancelling`, `pausing`) carried over from whatever
  the file was copied from. Replaced with the actual `OperationMode` members.
- Tests added for the throttle, the sensor-map lookup, `_round_native_value()`
  and key validation.

## 0.1.6 — 2026-06-24

- SmartShunt native-value precision adjusted: voltage and state of charge to 1
  decimal place, current and consumed Ah to integers.

## 0.1.5 — 2026-06-24

- `sensor.py` rounds the **native** value in `native_value` via
  `_round_native_value()` — precision by sensor key first, falling back to
  device class. `suggested_display_precision` (added in 0.1.4) only affects the
  displayed value and does not reduce recorder writes; rounding the stored
  native value is what collapses jittery ~1 Hz states into fewer rows.
- `consumed_ah`: removed the `energy_storage` device class. Ah is charge, not
  energy, and the class triggered a unit-validation warning. The sensor is now
  classless with an `mdi:battery-minus` icon.
- `consumed_energy`: state class changed from `total_increasing` to `total`.
  The value resets to 0 at full charge and is therefore not monotonic;
  `measurement` is not valid for the `energy` device class.

## 0.1.4 — 2026-06-22

- `UPDATE_THROTTLE_SECONDS` raised from 30 to 60.
- Both `(BATTERY, PERCENTAGE)` sensor descriptions given
  `suggested_display_precision=0`.

## 0.1.3 — 2026-06-22

- Added `UPDATE_THROTTLE_SECONDS` and `_make_throttled_update()` in
  `__init__.py`. Every BLE advertisement is still parsed, so the underlying
  data object stays current, but a real `SensorUpdate` is returned at most once
  per throttle window. In between, an empty `SensorUpdate` is returned and the
  passive-update processor writes no states. The first advertisement is always
  forwarded so entities register on startup.
