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
  `co2_emergency_ppm` (`co2_max_ppm` + `co2_emergency_margin_ppm`),
  `temp_mid_f` (the midpoint of the phase's temperature band), and the
  cutoffs' off points a deadband inside the band: `temp_heat_off_f`
  (`temp_min_f` + 1 °F), `temp_cool_off_f` (`temp_max_f` − 1 °F) and
  `humidity_dehumidify_off` (`humidity_max` − 3 %RH), each deadband at most a
  quarter of the band.
- Sensors are the telemetry keys plus the weather virtual sensors `mqtt.py`
  adds to each frame: `outdoor_temp_f`, `outdoor_humidity`,
  `outdoor_dew_point_f`, `outdoor_wind_mph`, `forecast_high_f`,
  `forecast_low_f`.
- Targets: `relay-01` and `light-01` are placeholders that resolve to the
  chamber's relay or lighting node (`resolve_node_target()`); in a chamber
  with no node of that role the rule does not fire. `plug-<role>` names a
  smart plug by id or role, either way the same plug. A chamber may list plug
  ids among its node ids: a role (a plug whose id is `plug-<role>` counts as
  one of the role's) then resolves to that chamber's own plug, else to a plug
  no chamber lists. For nodes in no chamber it resolves to a plug no chamber
  lists, else to one of a chamber that runs the same grow, never to a plug of
  a chamber that runs a grow of its own. Ending a grow switches off the plugs
  its rules reached that no other grow's rules reach, and every plug of the
  role when no grow is left. A rule whose target or channel cannot be
  reached is refused with 422 on create or update, as is a state other than
  `on` / `off` or a photoperiod other than `on` / `off`.
- `cron` is the 5-field form; with both day fields set, either one matching
  is enough, as in cron.

## How the engine applies them

Rules run on every live telemetry frame (not replayed or out-of-order ones),
highest priority first.

- **One owner per actuator:** the highest-priority rule whose condition holds
  owns an actuator; a lower-priority rule on it is skipped, also while the
  owner's command is in force (a frame without the owner's sensor, such as a
  relay node's own, does not end it). Equal priorities don't block each
  other. Cooldowns are kept per actuator, so each chamber's runs on its own.
- **Gates**, in order: phase and species scope; a sealed container (jar,
  agar, liquid culture, or a grow bag before browning or fruiting) skips
  rules on `fae`, `exhaust`, `circulation`, `aux` and the humidifier and
  dehumidifier plugs (by the plug's role, whatever name the rule uses);
  a phase with `fae_mode` `none` never drives `fae` or `exhaust`, and a
  schedule drives them only under `scheduled` or `continuous`;
  `requires_absent_target`; manual overrides.
- **Life-safety rules** (priority ≥ 20, no phase or species scope, absolute
  thresholds only: the CO2 Hard Ceiling) skip the sealed-container and
  `fae_mode` gates. With no active
  session, or one on a reference-only species, they are the only rules that
  run. The CO2 Hard Ceiling and the life-safety CO2 page trip at 40000 ppm,
  the full scale of the SCD30 and SCD4x (a saturated sensor reads exactly
  that); an MH-Z19C (5000 ppm full scale) never reaches it.
- **Pause** (`automation_paused`, also settable from the cloud) stops every
  actuator decision. Safety alerts still page.
- **Safety ceiling:** `safety_max_on_seconds` counts from the first ON; a trip
  switches the device off (a scene-driven light to the `colonization_dark`
  scene) and holds automation off it for 15 min, or for longer if a hold
  already in force runs longer.
- **Manual overrides** (`manual_overrides`, `/api/automation/overrides`) lock a
  target out of automation with a reason and an expiry of at most 24 h. The
  window is best given as `duration_sec`, which the Pi counts from now on its
  own clock; an absolute `expires_at` comes from the sender's clock, which
  may not agree with the Pi's. A new hold on the same target and channel
  replaces the one in force. A hold on one channel of a light also holds its
  scene rules. A hold counts under any name the rule's target resolves to: the
  node a placeholder stands for in each chamber, a plug's id or its role.
  `GET /api/automation/rules` lists with each rule the holds keeping it off
  its actuator (`held_by`). Ending a grow, which switches off what its rules
  switched on, leaves a held actuator as it is, the hold read the same way.
- **Firings** are recorded in `automation_firings` with their outcome
  (`GET /api/automation/firings`; per-rule counts over a window of days and
  each rule's newest firing: `GET /api/automation/firings/stats`; the write
  order is in
  [AGENTS.md](../AGENTS.md)).

## Built-in rules

SporePrint seeds 24 built-in rules. Each is offered to a Pi once: a new Pi
gets them all, a Pi seeded by an older release gets the ones that release did
not have, and a built-in the operator deleted is not added again (an addition
is logged as a warning). Scope "open" means the phases in which the substrate
sits in the chamber air: browning, primordia induction and fruiting.

| Rule | Priority | Scope | Fires when | Does |
|---|---|---|---|---|
| Humidity Boost | 10 | all | humidity < `humidity_min` | humidifier plug on, 300 s |
| Humidity Cut | 10 | all | humidity > `humidity_max` | humidifier plug off |
| Dehumidify | 10 | open | humidity > `humidity_max` | dehumidifier plug on, 600 s |
| Dehumidify Cutoff | 10 | open | humidity < `humidity_dehumidify_off` | dehumidifier plug off |
| Humidity Vent (no dehumidifier) | 9 | open | humidity > `humidity_max`, no dehumidifier paired | exhaust at PWM 180, 180 s |
| Mist (no humidifier) | 9 | open | humidity < `humidity_min`, no humidifier paired | `aux` pump, 8 s (30 s ceiling) |
| Circulation Cycle | 4 | primordia, fruiting | every `circulation_interval_min` (default 30) | circulation fan at PWM 160, 120 s |
| CO2 FAE Trigger | 8 | open | CO₂ > `co2_max_ppm` | FAE fan at PWM 200, 300 s |
| Emergency CO2 Exhaust | 20 | open | CO₂ > `co2_emergency_ppm` | exhaust at PWM 255, 600 s; notifies |
| CO2 Hard Ceiling | 21 | all | CO₂ ≥ 40000 ppm | exhaust at PWM 255, 600 s; notifies |
| CO2 Floor — Restrict FAE | 12 | all | CO₂ < `co2_min_ppm` (only where a floor is set) | FAE fan off |
| Scheduled FAE Cycle | 5 | primordia, fruiting | every `fae_interval_min` (default 20) | FAE fan at PWM 180 for `fae_duration_sec` |
| Heating Trigger | 9 | all | temp < `temp_min_f` | heater plug on, 600 s |
| Cooling Trigger | 9 | all | temp > `temp_max_f` | cooler plug on, 600 s |
| Heating Cutoff | 10 | all | temp ≥ `temp_heat_off_f` | heater plug off |
| Cooling Cutoff | 10 | all | temp ≤ `temp_cool_off_f` | cooler plug off |
| Photoperiod — Lights On | 3 | open | inside the light window (`light_hours_on` from 06:00 local) | scene `fruiting_standard` |
| Photoperiod — Lights Off | 3 | open | outside the light window | scene `colonization_dark`, off |
| Light Scene — Colonization Dark | 3 | substrate, grain, rest | always (a dark phase's window never opens) | scene `colonization_dark`, off |
| Lion's Mane Night Cool | 11 | primordia, `lions_mane` | 22:00–06:00 and temp > 60 °F | cooler plug on, 1800 s |
| Cordyceps Blue Light | 7 | primordia, fruiting, `cordyceps_militaris` | inside the light window | scene `cordyceps_blue` |
| Pre-cool for Hot Forecast | 11 | all | `forecast_high_f` > 90 and temp > `temp_mid_f` | cooler plug on, 900 s; notifies |
| Dry Weather Humidity Boost | 8 | primordia, fruiting | `outdoor_humidity` < 25 and humidity < `humidity_max` | humidifier plug on, 600 s |
| Heat Wave Warning | 15 | all | `forecast_high_f` > 95 and temp > `temp_mid_f` | cooler plug on, 1800 s; notifies |

Species quirks live in profile data the generic rules read (`co2_min_ppm` for
reishi antlers and king trumpet pinning, `fae_mode`). Lion's Mane Night Cool
and Cordyceps Blue Light are the only species-named rules. No rule reads
`light_spectrum`: Photoperiod — Lights On sends `fruiting_standard` in every
open phase whatever the profile asks for (shiitake fruiting's `blue_emphasis`
included), and only Cordyceps Blue Light switches a light to a blue scene
(`cordyceps_blue`).

## Changing a built-in rule

`seed_builtin_rules()` (`automation/service.py`) never rewrites a rule a Pi
already has, so an existing Pi keeps the rules it was first given. It offers
each name once and records the names in `user_settings`
(`automation_builtins_offered`). Releases before 5.2.0 recorded nothing; for a
Pi seeded by one, the names its release seeded (`SEEDED_BEFORE_V5`,
`SEEDED_V5_0_TO_V5_1` in `templates.py`) count as offered, so a built-in its
operator deleted or renamed does not come back.

To ship a changed built-in:

1. Copy its current form, exactly as it shipped, into `LEGACY_BUILTIN_RULES`
   or a `PRE_<change>_BUILTIN_RULES` table in `templates.py` (fold a new table
   into `_superseded_builtin_rules()`; no digits in the name), keyed by name.
2. Change it in `BUILTIN_RULES`.

At start-up a stored copy whose priority and behaviour (`_LEGACY_MATCH_FIELDS`
in `automation/service.py`) still match any superseded form
(`SUPERSEDED_BUILTIN_RULES`) is rewritten to the new form. An operator-edited
copy is never overwritten; the server logs a warning about it at every boot.

To stop shipping a built-in, move its last shipped form from `BUILTIN_RULES`
to `RETIRED_BUILTIN_RULES`. At start-up an unedited stored copy is switched
off, once per Pi (recorded in `automation_builtins_retired`), so an operator
can switch it back on; an edited copy is left running and named in the log.
Retired so far: Light Scene — Fruiting (the photoperiod rules replaced it) and
the reishi antler and king trumpet primordia CO2 restrict rules (CO2 Floor —
Restrict FAE replaced them).

A changed rule with no recorded old form silently stays old on every existing
install. `tests/test_builtin_rule_upgrades.py` replays the rules each release
seeded (`tests/fixtures/released_builtin_rules.json`) and fails on that; add a
release's seed there when its built-ins change.
