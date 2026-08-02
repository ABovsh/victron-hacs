# Changelog

All notable changes to this fork are listed here. Versions before 0.1.3 are
upstream [keshavdv/victron-hacs](https://github.com/keshavdv/victron-hacs) and
are not tracked in this file.

## 0.1.9 — 2026-08-03

First release whose CI has actually run. Enabling Actions on the fork surfaced
three failures that had been invisible since the fork was created.

- Hassfest rejected both `strings.json` and `translations/en.json`:
  `data['config']['entity']` is not a valid key — entity translations belong at
  the top level, not under `config`. The block was dead regardless: translating
  enum states requires a `translation_key` on the entity description and no
  description sets one, so the `operation_mode` names never reached the UI.
  Removed rather than relocated; wire it up properly if an MPPT ever needs it.
- Enabled issues on the repository. The HACS validator requires it and
  `manifest.json` already advertised an `issue_tracker` URL that led nowhere.
- HACS validation now ignores the `license` check as well as `brands`. Upstream
  keshavdv/victron-hacs ships no license, so this derived work has none to
  inherit and cannot grant one it does not hold.
- README: the HACS install badge still pointed at `owner=keshavdv`, so the one
  documented install path led back to upstream.
- Applied prettier to `README.md` and `CHANGELOG.md`; the pre-commit job had
  been failing on upstream's markdown formatting.
- Added GitHub topics and a repository description; the HACS validator requires
  topics, and a fork inherits neither from upstream.
- Test suite grown from 27 to 47 cases; every measured file is now at 100%
  line coverage. The additions cover the paths a user actually walks: setup and
  unload, the throttle reading its configured window, an options change
  rebuilding the entry, bluetooth discovery pre-filling the form, duplicate
  addresses aborting, both reconfigure outcomes, and both ways a bad key is
  caught. The one that matters most drives a parsed advertisement through the
  coordinator and asserts 52.7719 V lands in Home Assistant as `52.8` — the
  throttle, the description lookup and the native-value rounding in one piece.
- Connected to SonarCloud (`ABovsh_victron-hacs`): `sonar-project.properties`
  plus a `sonarcloud.yml` workflow gated on the `SONAR_ENABLED` repository
  variable, matching the other integrations in this account. `device.py` is
  excluded from coverage — only its battery-monitor branch runs on the hardware
  this fork is maintained against. README carries the usual badge row.

## 0.1.8 — 2026-08-02

- `async_unload_entry()` raised `KeyError` when `hass.data[DOMAIN]` was never
  populated, turning a setup that failed part-way into a second failure on
  teardown. Now tolerates both the domain and the entry being absent.
- CI actually runs the test suite. The `tests` job ended with
  `pytest ... --fixtures tests/` and a bare `tests/` on the following line: the
  missing line continuation meant pytest only _listed_ fixtures and the shell
  then tried to execute the directory. `DEFAULT_PYTHON` raised from 3.10 to
  3.13 (Home Assistant no longer supports 3.10), checkout/setup-python actions
  bumped to v4/v5, and `.github/workflows/constraints.txt` pins refreshed.
- `requirements_test.txt` no longer pins
  `pytest-homeassistant-custom-component==0.13.32`, which targeted Home
  Assistant 2024 and could not test the code as it actually runs. Dropped the
  bogus `serial` dependency (unrelated PyPI package; `pyserial` is the real
  one) and added `aiousbwatcher`, which Home Assistant's bluetooth import chain
  needs. `requirements_dev.txt` trimmed to what is used — `gitchangelog`,
  `mkdocs`, `codecov`, `coverage` and `pytest-cov` had no configuration or
  call site anywhere in the repository.
- `tests/test_config_flow.py` uses the `mock_bluetooth` fixture; without it the
  test needed a real HCI socket, which no CI runner has.
- Removed project-template leftovers: `Makefile` (104 lines, every target
  referencing a non-existent `pyproject.toml` and `pip install -e .[test]`),
  `.devcontainer/`, `.vscode/`, `scripts/develop`, `.github/labels.yml`,
  `.github/workflows/labeler.yml` and `.github/workflows/release-drafter.yml`.
- Removed dead code: `CannotConnect` and `InvalidAuth` (never raised, never
  caught) and `async_step_unignore()`, which called `self.async_abort()`
  without returning it and so returned `None` from a flow step. The now-unused
  `cannot_connect` and `invalid_auth` strings went with them.

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
