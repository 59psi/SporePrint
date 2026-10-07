# Species reference

Every automation rule, dashboard gauge, transcript and Builder answer
resolves to the active grow's species profile. The profiles are code:
[`server/app/species/models.py`](../server/app/species/models.py) (the data
model) and [`server/app/species/profiles.py`](../server/app/species/profiles.py)
(`BUILTIN_PROFILES`). This page explains that code and lists the setpoints of
the species whose automation is special. If it and `profiles.py` ever
disagree, the code wins; fix this page.

SporePrint ships 74 built-in species profiles: 30 gourmet, 11 medicinal,
25 active and 8 novelty. The active category is for education and research
purposes only: some species may be controlled where you live, and you are
responsible for following local law. Its profiles are not encouragement to
cultivate, possess or use any controlled organism, and this page does not
name them. Three profiles are reference only
(`chamber_cultivable = False`): chaga, *Pestalotiopsis microspora* and giant
puffball. The wizard never offers them for an indoor chamber, automation
does not manage a grow on one (only the CO₂ Hard Ceiling still runs), and the
dashboard shows their `cultivation_note` instead of a setpoint table.

## Data model

```python
class GrowPhase(str, Enum):
    AGAR = "agar"                                     # optional, in vessel
    LIQUID_CULTURE = "liquid_culture"                  # optional, in vessel
    GRAIN_COLONIZATION = "grain_colonization"          # optional, in vessel
    SUBSTRATE_COLONIZATION = "substrate_colonization"  # default start
    BROWNING = "browning"                              # shiitake only, no fallback
    COLD_STORAGE = "cold_storage"                      # colonized agar/LC/grain in the fridge
    PRIMORDIA_INDUCTION = "primordia_induction"
    FRUITING = "fruiting"
    REST = "rest"                                      # between flushes
    COMPLETE = "complete"

class PhaseParams:
    temp_min_f: float; temp_max_f: float
    temp_swing_required: bool; temp_swing_delta_f: float | None  # read by no rule yet
    humidity_min: float; humidity_max: float
    humidity_driven: bool = True          # False (cold storage): no low-RH alert
    co2_max_ppm: int                      # CO2 FAE Trigger above it
    co2_min_ppm: int | None               # CO2 floor: CO2 Floor — Restrict FAE
    co2_tolerance: str                    # "low" | "moderate" | "high"
    co2_sourced: bool; co2_source: str | None   # provenance of the CO2 figure
    co2_emergency_margin_ppm: int = 1000  # Emergency CO2 Exhaust at max + margin
    light_hours_on: float; light_hours_off: float
    light_spectrum: str                   # "none" | "daylight_6500k" | "blue_450nm" | "blue_emphasis"
    light_lux_target: int | None
    fae_mode: str                         # "none" | "passive" | "scheduled" | "continuous"
    fae_interval_min: int | None; fae_duration_sec: int | None
    circulation_interval_min: int | None
    substrate_moisture: str
    expected_duration_days: tuple[int, int]
    notes: str
    exit_reminder: str                    # manual step owed on leaving the phase

class SpeciesProfile:
    id; common_name; scientific_name
    category: str                         # "gourmet" | "medicinal" | "active" | "novelty"
    chamber_cultivable: bool; cultivation_note: str
    strain; substrate_types; colonization_visual_description
    contamination_risk_notes; pinning_trigger_description
    phases: dict[GrowPhase, PhaseParams]
    flush_count_typical; yield_notes; tags
    # plus: tldr, flavor_profile, edible, safety_warning, legal_disclaimer,
    # tek_guide, substrate_recipes, substrate_preference_ranking,
    # contamination_risks, regional_notes, photo_references
```

## Phase rules

In `server/app/sessions/service.py` unless noted.

- **Always enterable:** the colonization stages (agar, liquid culture, grain,
  substrate), cold storage and complete. A profile defines only the
  colonization stages it drives; a missing one means "no closet setpoints".
- **Need setpoints:** browning, primordia induction, fruiting and rest. A
  profile that lacks one borrows from `PHASE_PARAM_FALLBACKS`
  (primordia_induction ↔ fruiting; rest → fruiting, else primordia). With
  nothing to borrow, advancing is refused with 422 (`phase_error()` /
  `InvalidPhaseError`). The automation engine always runs rest with the
  lights off.
- **Browning** has no fallback: only a profile that defines it (shiitake) can
  enter it.
- **Cold storage** is species-agnostic: hold the fridge cold, drive nothing
  else.
- **Next phase** (`GET /api/sessions/{id}/next-phase`,
  `suggested_next_phase()`): after colonization a grow bag, monotub or tray
  goes to primordia induction (to browning first when the profile defines it),
  while agar, liquid culture and grain jars go to cold storage. Rest goes back
  to fruiting while more flushes are expected, else to complete.
- **Exit reminders:** a phase's `exit_reminder` (the shiitake soak) is offered
  by the daily 09:00 phase reminder once the phase has run its minimum
  duration, returned by next-phase, and logged as a `phase_exit_reminder`
  session event when the grow advances out of the phase.
- **Session fields:** `growth_form` (`antler` | `conk`) drives automation
  (reishi, below). `pinning_tek` (`bubble_wrap` | `fork_tek` | `cold_shock`)
  is stored on the session; no rule reads it.

## Species with special automation

All temperatures are °F. The tables give the values in `profiles.py`. CO₂ is
the phase's `co2_max_ppm` (and floor, where set). FAE names the profile's
`fae_mode` first. "In bag" phases run inside a sealed vessel, which the
closet can only hold near its temperature. Each heading line gives the
profile's `flush_count_typical` with the original spec's range, and the
difficulty from the profile's tags. The rules named here are in
[automation rules](automation-rules.md#built-in-rules).

### Blue Oyster (Pleurotus ostreatus var. columbinus)

`blue_oyster` · gourmet · straw, hardwood sawdust, masters mix · 3 flushes
(spec 3–4) · beginner

| Phase | Temp °F | RH % | CO₂ ppm | Light | FAE | Days |
|---|---|---|---|---|---|---|
| Substrate colonization | 68–75 | 90–100 (in bag) | ≤ 5000 | dark | passive (filter patch) | 10–14 |
| Primordia induction | 50–55 | 90–95 | **≤ 500** | 12/12 6500K | continuous (aggressive) | 3–5 |
| Fruiting | 55–65 | 85–92 | **≤ 700** | 12/12 6500K | continuous | 5–7 per flush |

- **CO₂ critical.** Above 700 ppm while fruiting the stems stretch and the
  caps stay small (etiolation). The CO2 FAE Trigger vents above the profile
  maximum and Emergency CO2 Exhaust runs at maximum + 1000 ppm. Long stems
  show up only in Claude's morphology notes and recommendations; there is no
  etiolation alert ([feature status](feature-status.md)).
- Pinning: cold shock to 50–55 °F plus a large FAE increase.
- Heavy spore load: Claude's `growth_rate` read counts flattening or
  upturned caps as slowing growth. Two slowing or ready reads in a row, or one
  `harvest_readiness` of `overdue`, send an INFO harvest notification
  (`vision/service.py` `harvest_signal()`).

### Pink Oyster (Pleurotus djamor)

`pink_oyster` · gourmet · tropical · 2 flushes (spec 2–3) · beginner

| Phase | Temp °F | RH % | CO₂ ppm | Light | FAE | Days |
|---|---|---|---|---|---|---|
| Substrate colonization | 75–85 | 90–100 (in bag) | ≤ 5000 | dark | passive (filter) | 7–10 |
| Fruiting | 70–85 | 85–95 | ≤ 700 | 12/12 6500K | continuous (heavy) | 5–7 per flush |

- **Dies below 40 °F and cannot be refrigerated.** Recording a pink oyster
  harvest sends a CRITICAL "process immediately" notification.
- No cold shock: tropical. The profile has no primordia phase, so a colonized
  bag goes straight to fruiting.

### King Trumpet (Pleurotus eryngii)

`king_trumpet` · gourmet · masters mix, supplemented hardwood · 2 flushes
(spec 2–3) · intermediate

| Phase | Temp °F | RH % | CO₂ ppm | Light | FAE | Days |
|---|---|---|---|---|---|---|
| Substrate colonization | 68–75 | 90–100 (in bag) | ≤ 5000 | dark | passive (filter) | 14–21 |
| Primordia induction | 50–55 | 90–95 | **1000–2000** | dim, 4/20 at 200 lux | passive (low FAE) | 5–7 |
| Fruiting | 58–65 | 80–90 | ≤ 1000 | 12/12 6500K | scheduled 5 min every 30 | 7–14 per flush |

- **Wants elevated CO₂ while pinning**, the opposite of the other oysters:
  fewer, larger fruits. The profile's `co2_min_ppm` (1000) drives the generic
  CO2 Floor — Restrict FAE rule.

### Lion's Mane (Hericium erinaceus)

`lions_mane` · gourmet (also used medicinally) · supplemented hardwood,
masters mix · 2 flushes (spec 2–3) · intermediate

| Phase | Temp °F | RH % | CO₂ ppm | Light | FAE | Days |
|---|---|---|---|---|---|---|
| Substrate colonization | 68–77 | 90–100 (in bag) | ≤ 10000 | dark | passive (filter) | 14–21 |
| Primordia induction | 55–65 | 90–95 | **≤ 500** | 12/12 at 300 lux | continuous (heavy) | 5–10 |
| Fruiting | 55–68 | 85–95 | **≤ 600** | 12/12 6500K | continuous | 7–14 per flush |

- **Needs a 6–10 °F daily swing to pin** (`temp_swing_delta_f` 8, e.g. 58 °F
  night / 66 °F day). Built as the Lion's Mane Night Cool rule: the cooler
  plug runs 22:00–06:00 while the closet is above 60 °F, in primordia only.
  A swing scheduler driven by `temp_swing_delta_f` is not built.
- **More CO₂-sensitive than the oysters:** high CO₂ grows coral-like
  branches instead of a pom-pom. Claude's morphology notes cover it; there is
  no dedicated coral detector.
- Its mycelium is noticeably finer and less opaque than other species'. That
  is normal, not contamination. Early pinning inside the bag is common.

### Shiitake (Lentinula edodes)

`shiitake` · gourmet · supplemented hardwood (oak), logs · 4 flushes
(spec 3–6) · intermediate

| Phase | Temp °F | RH % | CO₂ ppm | Light | FAE | Days |
|---|---|---|---|---|---|---|
| Substrate colonization | 68–77 | 90–100 (in bag) | ≤ 10000 | dark | passive (filter) | **30–60** |
| Browning/popcorning | 60–70 | 70–80 | ≤ 2000 | 12/12 daylight (indirect OK) | passive | 7–14 |
| Primordia induction | 50–60 | 85–95 | ≤ 700 | 12/12 6500K | scheduled 5 min every 30 | 5–10 |
| Fruiting | 50–65 | 80–90 | ≤ 1000 | 12/12, blue emphasis | scheduled 5 min every 30 | 7–14 per flush |

- **Browning is its own phase** (`GrowPhase.BROWNING`). Out of its bag, a
  colonized block grows a brown skin and cannot fruit until it is done.
  Next-phase suggests substrate colonization → browning → primordia
  induction. In browning, the vision prompt tells Claude the brown, popcorned
  skin is normal and asks for `browning_percent`. At 90 % the grow logs
  `browning_complete` and sends an INFO notification.
- Pinning is a manual cold-water soak (35–50 °F for 12–24 h). It is browning's
  `exit_reminder` (see [Phase rules](#phase-rules)).

### Reishi (Ganoderma lingzhi)

`reishi` · medicinal · supplemented hardwood, grain · one growth ·
intermediate (spec; no difficulty tag)

| Phase | Temp °F | RH % | CO₂ ppm | Light | FAE | Days |
|---|---|---|---|---|---|---|
| Substrate colonization | 75–85 | 90–100 (in bag) | ≤ 5000 | dark | passive (filter) | 14–21 |
| Antler formation (`primordia_induction`) | 75–85 | 85–95 | **1500–5000** (floor 1500) | minimal, 2/22 | none (minimal) | 30–60 |
| Conk formation (`fruiting`) | 70–80 | 85–95 | ≤ 800 | 12/12 6500K | scheduled 5 min every 30 | 60–90 |

- **CO₂ controls the shape.** High CO₂ grows antlers (finger-like, prized
  for extracts); low CO₂ with FAE grows a conk (shelf). The session's
  `growth_form` picks it: the engine's `_apply_growth_form` keeps an `antler`
  session on the CO₂-floor parameters through primordia and fruiting, and a
  `conk` session on the low-CO₂ parameters even while pinning.
- Expect 90+ day sessions.

### Cordyceps militaris

`cordyceps_militaris` · medicinal · brown rice · 1 flush (spec 1–2) ·
advanced

| Phase | Temp °F | RH % | CO₂ ppm | Light | FAE | Days |
|---|---|---|---|---|---|---|
| Substrate colonization | 68–75 | 90–100 (in container) | ≤ 5000 | dark | none | 14–21 |
| Primordia induction | 60–65 | 90–95 | ≤ 800 | **12/12 blue 450 nm** | scheduled 5 min every 30 | 7–14 |
| Fruiting | 60–68 | 85–95 | ≤ 800 | **16/8 blue 450 nm** | scheduled 5 min every 30 | 30–45 |

- **Needs blue light at 440–460 nm** to fruit; daylight is not enough. The
  lighting personality has an independent `blue` channel and a
  `cordyceps_blue` scene, which the Cordyceps Blue Light rule holds during
  the light window. A generic ~465 nm strip will not do (build-guide
  troubleshooting).
- Quality shows as bright orange stromata. An orange-saturation metric is not
  built; Claude's read is the only judge.

### Turkey Tail (Trametes versicolor)

`turkey_tail` · medicinal · supplemented hardwood, logs · 3 flushes
(spec 2–4) · beginner (spec: beginner to intermediate)

| Phase | Temp °F | RH % | CO₂ ppm | Light | FAE | Days |
|---|---|---|---|---|---|---|
| Substrate colonization | 70–80 | 90–100 (in bag) | ≤ 5000 | dark | passive (filter) | 14–21 |
| Fruiting | 65–75 | 80–90 | ≤ 1000 | 12/12 6500K | scheduled 5 min every 30 | 14–28 per flush |

- Forgiving. Colour-banding progress tracking is not built.

## Custom profiles

- Built-ins are read-only: `PUT /api/species/{id}` on one returns 409 and
  `DELETE` refuses it. Clone a built-in under a new id with
  `POST /api/species`, then edit the copy with `PUT`.
- Import is `POST /api/species` with the profile JSON; export is
  `GET /api/species/{id}`. The dashboard has no profile editor or
  import/export buttons yet.
