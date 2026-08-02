# Victron Instant Readout Integration

> Home Assistant integration for Victron devices with Instant Readout enabled — SmartShunt, BMV, MPPT, Smart Battery Sense, Battery Protect, Orion DC/DC, SmartLithium, Lynx BMS. Passive Bluetooth, no connection to the device, no cloud.

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/version-0.1.10-blue?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.11%2B-41BDF5?style=for-the-badge&logo=home-assistant)

[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_victron-hacs&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=ABovsh_victron-hacs)
[![Reliability](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_victron-hacs&metric=reliability_rating)](https://sonarcloud.io/component_measures?id=ABovsh_victron-hacs&metric=reliability_rating)
[![Security](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_victron-hacs&metric=security_rating)](https://sonarcloud.io/component_measures?id=ABovsh_victron-hacs&metric=security_rating)
[![Maintainability](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_victron-hacs&metric=sqale_rating)](https://sonarcloud.io/component_measures?id=ABovsh_victron-hacs&metric=sqale_rating)
[![Coverage](https://img.shields.io/sonar/coverage/ABovsh_victron-hacs?server=https%3A%2F%2Fsonarcloud.io&style=for-the-badge&logo=sonarcloud&label=coverage)](https://sonarcloud.io/component_measures?id=ABovsh_victron-hacs&metric=coverage)

- Issues: [github.com/ABovsh/victron-hacs/issues](https://github.com/ABovsh/victron-hacs/issues)
- Changes: [CHANGELOG.md](CHANGELOG.md)

## Why this fork

Fork of [keshavdv/victron-hacs](https://github.com/keshavdv/victron-hacs). The
upstream integration is a thin passive-BLE listener: it pushes a fresh state to
Home Assistant on **every** advertisement, and Victron devices advertise at
roughly 1 Hz with no scan-interval or throttle option. On a SmartShunt that is
around 86 000 state writes per entity per day, which made it one of the largest
single sources of recorder growth in the author's installation.

What this fork changes:

- **Throttling.** A configurable minimum interval between the states forwarded
  to Home Assistant. Every advertisement is still parsed, so the data object
  stays current — only the write to the recorder is suppressed. State and alarm
  transitions bypass the throttle and are forwarded immediately, so nothing
  event-like is ever dropped.
- **Native-value rounding.** The recorder stores a row on every state _change_,
  so trailing jitter digits are what actually create the rows.
  `suggested_display_precision` does not help — it only rounds the display.
  This fork rounds the stored value per sensor key and device class.
- **Sensor metadata fixes.** Device and state classes corrected where the
  upstream combinations produced HA unit-validation warnings (`consumed_ah`,
  `consumed_energy`).
- **Robustness.** An unknown sensor key coming from the `victron_ble` library no
  longer raises inside the coordinator's update path, where a ~1 Hz exception
  storm would otherwise stop the device from updating at all. Unloading an entry
  whose setup never completed no longer raises either.
- **Less repository.** The upstream tree carried a project template's leftovers —
  a `Makefile` whose every target referenced a `pyproject.toml` that does not
  exist, a devcontainer, VS Code settings, a release drafter and a PR labeler for
  a fork that cuts no releases and takes no pull requests. All removed. The test
  job in CI never ran the tests (a missing line continuation turned the last
  argument into `pytest --fixtures`, which only lists fixtures); it runs them now,
  on the Python version Home Assistant actually requires.
- **Setup and reconfiguration.** The encryption key is validated at setup time
  instead of silently producing a device with no entities, and the key and
  throttle interval can be changed afterwards without deleting and re-adding
  the device.

### Upstream issues fixed here

The upstream project has not had a commit since December 2025 and carries 58
open issues. These are the ones that were reproducible in the code and are
fixed in this fork:

| Upstream                                                                                                                                                                                                                                           | Symptom                                                                                                                             | Fix                                                                              |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [#209](https://github.com/keshavdv/victron-hacs/issues/209), [#156](https://github.com/keshavdv/victron-hacs/issues/156), [#212](https://github.com/keshavdv/victron-hacs/issues/212), [#131](https://github.com/keshavdv/victron-hacs/issues/131) | One advertisement the library cannot parse raises out of the coordinator, thousands of times, and every sensor on that device stops | The parse is guarded per advertisement and warned about once per device          |
| [#140](https://github.com/keshavdv/victron-hacs/issues/140)                                                                                                                                                                                        | Switching a solar charger's load output off leaves the load sensor stuck at its last non-zero reading, then unavailable             | `is not None` instead of a truthiness test — 0 A is a reading                    |
| [#188](https://github.com/keshavdv/victron-hacs/issues/188)                                                                                                                                                                                        | A wrong encryption key is accepted; the device is created with no entities and nothing in the UI says why                           | The key is validated at setup, against a live advertisement when one is in range |
| [#105](https://github.com/keshavdv/victron-hacs/issues/105)                                                                                                                                                                                        | Update rate is not adjustable                                                                                                       | Per-device throttle in the options flow, `0` to disable                          |
| —                                                                                                                                                                                                                                                  | Solar yield reported in watt-hours but tagged as an electric current                                                                | Corrected to the energy device class                                             |

Not fixable here, because the defect is in the `victron_ble` library rather
than this integration: [#154](https://github.com/keshavdv/victron-hacs/issues/154)
(Battery Protect `OutputState.OFF` is 4 where the device sends 0) and
[#210](https://github.com/keshavdv/victron-hacs/issues/210) (Phoenix IP43 AC
current is ten times too high). The parse guard above at least stops the first
one from taking the device down.

**A known limitation, not a bug:** `consumed_energy` is `current voltage × consumed Ah`. Real energy is the integral of V×I over time, and the SmartShunt
does not broadcast it, so this is an estimate that drifts with the voltage
swing of your bank — roughly ±8 % on a 48 V LiFePO₄ pack. It is kept because
removing it would break existing dashboards. Use `consumed_ah` when you need
the number the shunt actually measured.

Changes are tracked in [CHANGELOG.md](CHANGELOG.md). This fork is installed as a
HACS **custom repository**, not from the HACS default list.

Supported Devices & Entities:

- SmartShunt 500A/500mv and BMV-712/702 provide the following data:
  - Voltage
  - Alarm status
  - Current
  - Remaining time (mins)
  - State of charge (%)
  - Consumed amp hours
  - Auxilary input mode and value (temperature, midpoint voltage, or starter battery voltage)
- Smart Battery Sense
  - Voltage
  - Temperature (°C)
- Smart Battery Protect
  - Input Voltage
  - Output Voltage
  - Output State
  - Device State
  - Charger Error
  - Alarm Reason
  - Warning Reason
  - Off Reason
- MPPT/Solar Charger
  - Charger State (Off, Bulk, Absorption, Float)
  - Battery Voltage (V)
  - Battery Charging Current (A)
  - Solar Power (W)
  - Yield Today (Wh)
  - External Device Load (A)
- DC/DC Charger
  - Input Voltage
  - Output Voltage
  - Operation Mode
  - Charger Error
  - Off Reason
- AC Charger
  - Output Voltage 1|2|3
  - Output Current 1|2|3
  - Operation Mode
  - Temperature (°C)
  - AC Current
- SmartLithium
  - Battery Voltage
  - Battery Temperature (°C)
  - Cell Voltages (1-16)
  - Balancer Status
- Lynx Smart BMS
  - Voltage
  - Current
  - State of charge (%)
  - Remaining time (mins)
  - Consumed amp hours
  - Power

# Installation

## Manual

1. Clone the repository to your machine and copy the contents of custom_components/ to your config directory
2. Restart Home Assistant
3. Setup integration via the integration page.

## HACS

1. Add this fork as a HACS **custom repository**, then add the integration:
   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ABovsh&repository=victron-hacs&category=integration)
2. Restart Home Assistant
3. Setup integration via the integration page.

## 🛰️ Adding a Victron Device

After installing the integration, follow these steps to connect your Victron equipment via Bluetooth.

### 🔍 Device Discovery & Setup

1. Ensure your Home Assistant instance has working Bluetooth support.
2. Go to **Settings > Devices & Services**, and look for a discovered device such as `Victron VE.Direct`, `SmartShunt`, or `SmartSolar`.
3. Click **Add** and give the device a name and enter the corresponding encryption key (see below).
4. **Tip:** Home Assistant will show the **MAC address** of the discovered device. Use this to confirm which device you’re configuring by comparing it with the MAC address shown in the VictronConnect app.

---

### 🔑 Get the MAC Address and Encryption Key

You can find both values using the **VictronConnect App**:

1. Open the VictronConnect App and connect to your device.
2. Tap the **gear icon** (⚙️) in the top right corner.
3. Tap the **three-dot menu** (⋮) and select **Product Info**.
4. Scroll to the **Encryption Data** section.
5. Tap **SHOW** to reveal:
   - **MAC Address**
   - **Encryption Key** (called _Advertisement Key_ in this integration)

> 💡 Save these values to paste into the Home Assistant configuration screen when prompted.

---

### 🧪 Troubleshooting

- Ensure your Home Assistant host supports Bluetooth (e.g., Home Assistant OS or compatible USB adapter).
- If discovery fails, try restarting Home Assistant or moving your system closer to the Victron hardware.
- Check **Settings > System > Logs** for messages from the `victron_ble` integration.
