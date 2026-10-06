# Automation rules

Rules are data: **(phase + sensor + schedule) → actuator command**. The model
is [`server/app/automation/models.py`](../server/app/automation/models.py),
the built-ins are [`automation/templates.py`](../server/app/automation/templates.py)
(`BUILTIN_RULES`), and the engine is `automation/engine.py`. Rules are
created, edited, toggled and deleted through `/api/automation/rules`; the
dashboard lists and toggles them but has no editor
([feature status](feature-status.md)). If this page and the code disagree,
the code wins; fix this page.

## Rule model

```text
AutomationRule:
  name, description, enabled, priority
  applies_to_phases, applies_to_species     # None = every phase / species
  requires_absent_target                    # fire only while this target is NOT paired
  condition: threshold | schedule | compound (AND | OR of conditions)
    threshold: sensor, operator (lt gt lte gte eq), value | profile_ref
    schedule:  cron | interval_min | time_range | photoperiod ("on" | "off", photoperiod_start)
               | profile_interval_ref (a PhaseParams field holding minutes)
  action: target, channel, state, pwm, duration_sec | duration_profile_ref, ramp_sec, scene
          | vendor action: vendor_slug, vendor_action, vendor_params (target = override key)
  cooldown_seconds, safety_max_on_seconds, notification, log_to_session
```

- `profile_ref` names a field of the active phase's `PhaseParams`
  ([species reference](species-reference.md#data-model)), or a derived one:
  `co2_emergency_ppm` (`co2_max_ppm` + `co2_emergency_margin_ppm`) and
  `temp_mid_f` (the midpoint of the phase's temperature band).
- Sensors are the telemetry keys plus the weather virtual sensors `mqtt.py`
  adds to each frame: `outdoor_temp_f`, `outdoor_humidity`,
  `outdoor_dew_point_f`, `outdoor_wind_mph`, `forecast_high_f`,
  `forecast_low_f`.
- Targets: `relay-01` and `light-01` are placeholders that resolve to the
  chamber's relay or lighting node (`resolve_node_target()`); `plug-<role>`
  names a smart plug by id or role. A rule whose target or channel cannot be
  reached is refused with 422 on create or update.

## How the engine applies them

Rules run on every live telemetry frame (not replayed or out-of-order ones),
highest priority first.

- **One owner per actuator:** the highest-priority rule whose condition holds
  owns an actuator; a lower-priority rule on it is skipped. Equal priorities
  don't block each other.
- **Gates**, in order: phase and species scope; a sealed container (jar,
  agar, or a grow bag before browning or fruiting) skips rules on `fae`,
  `exhaust`, `circulation`, `aux` and the humidifier and dehumidifier plugs;
  a phase with `fae_mode` `none` never drives `fae` or `exhaust`, and a
  schedule drives them only under `scheduled` or `continuous`;
  `requires_absent_target`; manual overrides.
- **Life-safety rules** (priority ≥ 20, no phase or species scope, absolute
  thresholds only: the CO2 Hard Ceiling) skip the sealed-container and
  `fae_mode` gates. With no active
  session, or one on a reference-only species, they are the only rules that
  run.
- **Pause** (`automation_paused`, also settable from the cloud) stops every
  actuator decision. Safety alerts still page.
- **Safety ceiling:** `safety_max_on_seconds` counts from the first ON; a trip
  switches the device off and holds automation off it for 15 min.
- **Manual overrides** (`manual_overrides`, `/api/automation/overrides`) lock a
  target out of automation with a reason and an expiry of at most 24 h.
- **Firings** are recorded in `automation_firings` with their outcome
  (`GET /api/automation/firings`; the write order is in
  [AGENTS.md](../AGENTS.md)).

## Built-in rules

SporePrint seeds 24 built-in rules into an empty `automation_rules` table.
Scope "open" means the phases in which the substrate sits in the chamber air:
browning, primordia induction and fruiting.

| Rule | Priority | Scope | Fires when | Does |
|---|---|---|---|---|
| Humidity Boost | 10 | all | humidity < `humidity_min` | humidifier plug on, 300 s |
| Humidity Cut | 10 | all | humidity > `humidity_max` | humidifier plug off |
| Dehumidify | 10 | open | humidity > `humidity_max` | dehumidifier plug on, 600 s |
| Dehumidify Cutoff | 10 | open | humidity < `humidity_max` | dehumidifier plug off |
| Humidity Vent (no dehumidifier) | 9 | open | humidity > `humidity_max`, no dehumidifier paired | exhaust at PWM 180, 180 s |
| Mist (no humidifier) | 9 | open | humidity < `humidity_min`, no humidifier paired | `aux` pump, 8 s (30 s ceiling) |
| Circulation Cycle | 4 | primordia, fruiting | every `circulation_interval_min` (default 30) | circulation fan at PWM 160, 120 s |
| CO2 FAE Trigger | 8 | open | CO₂ > `co2_max_ppm` | FAE fan at PWM 200, 300 s |
| Emergency CO2 Exhaust | 20 | open | CO₂ > `co2_emergency_ppm` | exhaust at PWM 255, 600 s; notifies |
| CO2 Hard Ceiling | 21 | all | CO₂ > 40000 ppm | exhaust at PWM 255, 600 s; notifies |
| CO2 Floor — Restrict FAE | 12 | all | CO₂ < `co2_min_ppm` (only where a floor is set) | FAE fan off |
| Scheduled FAE Cycle | 5 | primordia, fruiting | every `fae_interval_min` (default 20) | FAE fan at PWM 180 for `fae_duration_sec` |
| Heating Trigger | 9 | all | temp < `temp_min_f` | heater plug on, 600 s |
| Cooling Trigger | 9 | all | temp > `temp_max_f` | cooler plug on, 600 s |
| Heating Cutoff | 10 | all | temp ≥ `temp_min_f` | heater plug off |
| Cooling Cutoff | 10 | all | temp ≤ `temp_max_f` | cooler plug off |
| Photoperiod — Lights On | 3 | open | inside the light window (`light_hours_on` from 06:00 local) | scene `fruiting_standard` |
| Photoperiod — Lights Off | 3 | open | outside the light window | scene `colonization_dark`, off |
| Light Scene — Colonization Dark | 3 | substrate, grain | always (a dark phase's window never opens) | scene `colonization_dark`, off |
| Lion's Mane Night Cool | 11 | primordia, `lions_mane` | 22:00–06:00 and temp > 60 °F | cooler plug on, 1800 s |
| Cordyceps Blue Light | 7 | primordia, fruiting, `cordyceps_militaris` | inside the light window | scene `cordyceps_blue` |
| Pre-cool for Hot Forecast | 11 | all | `forecast_high_f` > 90 and temp > `temp_mid_f` | cooler plug on, 900 s; notifies |
| Dry Weather Humidity Boost | 8 | primordia, fruiting | `outdoor_humidity` < 25 and humidity < `humidity_max` | humidifier plug on, 600 s |
| Heat Wave Warning | 15 | all | `forecast_high_f` > 95 and temp > `temp_mid_f` | cooler plug on, 1800 s; notifies |

Species quirks live in profile data the generic rules read (`co2_min_ppm` for
reishi antlers and king trumpet pinning, `light_spectrum`, `fae_mode`). Lion's
Mane Night Cool and Cordyceps Blue Light are the only species-named rules.

## Changing a built-in rule

`seed_builtin_rules()` (`automation/service.py`) seeds only an empty table,
so an existing Pi keeps the rules it was first given. To ship a changed
built-in:

1. Copy its current form, exactly as it shipped, into `LEGACY_BUILTIN_RULES`
   or a `PRE_<change>_BUILTIN_RULES` table in `templates.py` (fold a new table
   into `_superseded_builtin_rules()`), keyed by name.
2. Change it in `BUILTIN_RULES`.

At start-up a stored copy whose priority and behaviour (`_LEGACY_MATCH_FIELDS`
in `automation/service.py`) still match any superseded form
(`SUPERSEDED_BUILTIN_RULES`) is rewritten to the new form. An operator-edited
copy is never overwritten; the server logs a warning about it at every boot.
A changed rule with no recorded old form silently stays old on every
existing install, and no test catches that.
