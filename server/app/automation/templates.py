"""Built-in automation rule templates seeded on startup."""

from .models import (
    AutomationRule,
    RuleCondition,
    RuleAction,
    ConditionType,
    ThresholdCondition,
    ScheduleCondition,
    CompoundCondition,
    CompoundOp,
)

BUILTIN_RULES: list[AutomationRule] = [
    # ─── Humidity Control ────────────────────────────────────────
    AutomationRule(
        name="Humidity Boost",
        description="Activate humidifier when humidity drops below species target minimum",
        priority=10,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="humidity",
                operator="lt",
                profile_ref="humidity_min",
            ),
        ),
        action=RuleAction(target="plug-humidifier", state="on", duration_sec=300),
        cooldown_seconds=120,
        safety_max_on_seconds=1800,
        notification=False,
        log_to_session=True,
    ),
    AutomationRule(
        name="Humidity Cut",
        description="Deactivate humidifier when humidity exceeds species target maximum",
        priority=10,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="humidity",
                operator="gt",
                profile_ref="humidity_max",
            ),
        ),
        action=RuleAction(target="plug-humidifier", state="off"),
        cooldown_seconds=60,
        log_to_session=True,
    ),
    # Humidity was ONE-DIRECTIONAL until now: the humidifier turned on and off,
    # but nothing REMOVED humidity. A sealed chamber pinned at 95% RH is a
    # contamination event, and Tier 3 ships a dehumidifier plug for exactly it.
    AutomationRule(
        name="Dehumidify",
        description="Run the dehumidifier when humidity exceeds the species maximum",
        priority=10,
        applies_to_phases=["primordia_induction", "fruiting"],
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="gt", profile_ref="humidity_max"),
        ),
        action=RuleAction(target="plug-dehumidifier", state="on", duration_sec=600),
        cooldown_seconds=300,
        safety_max_on_seconds=3600,
        log_to_session=True,
    ),
    AutomationRule(
        name="Dehumidify Cutoff",
        description="Stop the dehumidifier once humidity is back within range",
        priority=10,
        applies_to_phases=["primordia_induction", "fruiting"],
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="lt", profile_ref="humidity_max"),
        ),
        action=RuleAction(target="plug-dehumidifier", state="off"),
        cooldown_seconds=60,
        log_to_session=True,
    ),
    # Graceful degradation: no dehumidifier? Shed humidity by exchanging chamber
    # air with (drier) ambient using the exhaust fan. This is how a monotub
    # without a dehumidifier is actually managed. `requires_absent_target` makes
    # it go silent the moment a real dehumidifier is paired, so the two never
    # fight. Note the tradeoff: venting also sheds CO2 and heat — so this is
    # fruiting-only (colonization's fae_mode=none already blocks it via the
    # air-exchange guard) and deliberately gentler than the emergency exhaust.
    AutomationRule(
        name="Humidity Vent (no dehumidifier)",
        description="Vent moist air with the exhaust fan when humidity is high and no dehumidifier is present",
        priority=9,
        applies_to_phases=["primordia_induction", "fruiting"],
        requires_absent_target="plug-dehumidifier",
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="gt", profile_ref="humidity_max"),
        ),
        action=RuleAction(target="relay-01", channel="exhaust", state="on", pwm=180, duration_sec=180),
        cooldown_seconds=600,
        safety_max_on_seconds=900,
        log_to_session=True,
    ),
    # Circulation fan — kept a steady low cycle during fruiting so the chamber
    # doesn't stratify (CO2 pools low, RH pockets form, pins dry unevenly). It
    # is NOT fresh-air exchange — it stirs the air already in the chamber — so
    # it runs even when fae_mode="none" holds the FAE/exhaust fans off. Cadence
    # is species-driven via the scheduler; falls back to the literal.
    AutomationRule(
        name="Circulation Cycle",
        description="Periodic internal air circulation during fruiting to prevent stratification",
        priority=4,
        applies_to_phases=["primordia_induction", "fruiting"],
        condition=RuleCondition(
            type=ConditionType.SCHEDULE,
            schedule=ScheduleCondition(profile_interval_ref="circulation_interval_min", interval_min=30),
        ),
        action=RuleAction(target="relay-01", channel="circulation", state="on", pwm=160, duration_sec=120),
        cooldown_seconds=600,
        log_to_session=True,
    ),
    # Misting pump (relay aux / GPIO 14) as the HUMIDIFIER's fallback — symmetric
    # with the exhaust-vent fallback for the dehumidifier. If no humidifier plug
    # is paired, a brief mist raises RH. Gated HARD: short pulse, long cooldown,
    # tight safety cutoff — over-misting causes bacterial blotch, and we have no
    # substrate-moisture sensor to close the loop, so this stays conservative and
    # only runs when there is genuinely no other way to add humidity.
    AutomationRule(
        name="Mist (no humidifier)",
        description="Brief misting pulse when humidity is low and no humidifier plug is present",
        priority=9,
        applies_to_phases=["primordia_induction", "fruiting"],
        requires_absent_target="plug-humidifier",
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="lt", profile_ref="humidity_min"),
        ),
        action=RuleAction(target="relay-01", channel="aux", state="on", pwm=255, duration_sec=8),
        cooldown_seconds=600,
        safety_max_on_seconds=30,
        log_to_session=True,
    ),

    # ─── CO2 / FAE Control ──────────────────────────────────────
    AutomationRule(
        name="CO2 FAE Trigger",
        description="Vent when CO2 exceeds the species' fruiting/pinning ceiling",
        priority=8,
        # Fruiting phases only. Colonization WANTS high CO2 (5000-15000ppm at
        # zero FAE — Stamets & Chilton); this rule used to have no phase gate and
        # latched the fan on from day one of the spawn run, drying the substrate
        # and venting the CO2 the mycelium needs. The fae_mode guard in the engine
        # backstops this, but the phase gate makes the intent explicit.
        applies_to_phases=["primordia_induction", "fruiting"],
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="co2_ppm",
                operator="gt",
                profile_ref="co2_max_ppm",
            ),
        ),
        action=RuleAction(target="relay-01", channel="fae", state="on", pwm=200, duration_sec=300),
        cooldown_seconds=300,
        safety_max_on_seconds=1800,
        log_to_session=True,
    ),
    AutomationRule(
        name="Emergency CO2 Exhaust",
        description="Hard exhaust when CO2 runs above the species' emergency edge",
        priority=20,
        # Fruiting-only AND species-relative. The old hardcoded 3000 was normal —
        # even low — for a reishi antler fruiting (1000-10000ppm) or a maitake
        # rosette, so it fought species that legitimately hold CO2 high. Now it
        # fires at co2_emergency_ppm = the phase's co2_max_ppm + its margin, so
        # "emergency" means the same distance above target for every species.
        applies_to_phases=["primordia_induction", "fruiting"],
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="co2_ppm",
                operator="gt",
                profile_ref="co2_emergency_ppm",
            ),
        ),
        action=RuleAction(target="relay-01", channel="exhaust", state="on", pwm=255, duration_sec=600),
        cooldown_seconds=120,
        notification=True,
        log_to_session=True,
    ),
    AutomationRule(
        name="CO2 Hard Ceiling",
        description="Absolute exhaust backstop — vents no matter the species or phase",
        priority=21,
        # The species-relative emergency above needs a phase profile to resolve.
        # This is the profile-independent floor under it: a level (40000ppm) far
        # above any legitimate cultivation band, including a 10-40k colonization,
        # so it never fights a real grow — but it still protects the equipment
        # and anyone in the room if CO2 runs away with no active grow profile.
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="co2_ppm", operator="gt", value=40000),
        ),
        action=RuleAction(target="relay-01", channel="exhaust", state="on", pwm=255, duration_sec=600),
        cooldown_seconds=120,
        notification=True,
        log_to_session=True,
    ),
    AutomationRule(
        name="Scheduled FAE Cycle",
        description="Periodic FAE — period and duration come from the species' grow profile",
        priority=5,
        applies_to_phases=["primordia_induction", "fruiting"],
        condition=RuleCondition(
            type=ConditionType.SCHEDULE,
            # The profile already states how often each phase wants fresh air
            # (fae_interval_min: 20 for oyster fruiting, 30 for primordia…).
            # This was hardcoded to 20 for every species and every phase, so the
            # numbers in the grow profile were decorative. interval_min stays as
            # the fallback for a profile that doesn't specify one.
            schedule=ScheduleCondition(profile_interval_ref="fae_interval_min", interval_min=20),
        ),
        action=RuleAction(
            target="relay-01", channel="fae", state="on", pwm=180,
            duration_profile_ref="fae_duration_sec", duration_sec=300,
        ),
        cooldown_seconds=600,
        log_to_session=True,
    ),

    # ─── Temperature Control ────────────────────────────────────
    AutomationRule(
        name="Heating Trigger",
        description="Activate heater when temperature drops below species target minimum",
        priority=9,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="temp_f",
                operator="lt",
                profile_ref="temp_min_f",
            ),
        ),
        action=RuleAction(target="plug-heater", state="on", duration_sec=600),
        cooldown_seconds=300,
        safety_max_on_seconds=3600,
        log_to_session=True,
    ),
    AutomationRule(
        name="Cooling Trigger",
        description="Activate cooler when temperature exceeds species target maximum",
        priority=9,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="temp_f",
                operator="gt",
                profile_ref="temp_max_f",
            ),
        ),
        action=RuleAction(target="plug-cooler", state="on", duration_sec=600),
        cooldown_seconds=300,
        safety_max_on_seconds=3600,
        log_to_session=True,
    ),
    AutomationRule(
        name="Heating Cutoff",
        description="Turn off heater when temperature reaches target",
        priority=10,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="temp_f",
                operator="gte",
                profile_ref="temp_min_f",
            ),
        ),
        action=RuleAction(target="plug-heater", state="off"),
        cooldown_seconds=60,
        log_to_session=False,
    ),
    AutomationRule(
        name="Cooling Cutoff",
        description="Turn off cooler when temperature drops to target",
        priority=10,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="temp_f",
                operator="lte",
                profile_ref="temp_max_f",
            ),
        ),
        action=RuleAction(target="plug-cooler", state="off"),
        cooldown_seconds=60,
        log_to_session=False,
    ),

    # ─── Photoperiod ────────────────────────────────────────────
    # These two rules ARE the light cycle. The window comes from the species'
    # light_hours_on for the active phase, so a 12/12 species runs 12/12 and a
    # 16/8 species runs 16/8 from the same pair of rules.
    #
    # Previously both light rules were `interval_min=60` re-assertions of a
    # fixed scene, which meant the profile's light_hours_on/off were never read:
    # fruiting lights were simply ON forever, and there was no dark period at
    # all. Photoperiod is not cosmetic for mushrooms — it's a fruiting trigger.
    AutomationRule(
        name="Photoperiod — Lights On",
        description="Lights on during the species' light window for this phase",
        priority=3,
        applies_to_phases=["primordia_induction", "fruiting"],
        condition=RuleCondition(
            type=ConditionType.SCHEDULE,
            schedule=ScheduleCondition(photoperiod="on", photoperiod_start="06:00"),
        ),
        action=RuleAction(target="light-01", scene="fruiting_standard"),
        cooldown_seconds=1800,
        log_to_session=True,
    ),
    AutomationRule(
        name="Photoperiod — Lights Off",
        description="Lights off outside the species' light window (the dark period)",
        priority=3,
        applies_to_phases=["primordia_induction", "fruiting"],
        condition=RuleCondition(
            type=ConditionType.SCHEDULE,
            schedule=ScheduleCondition(photoperiod="off", photoperiod_start="06:00"),
        ),
        action=RuleAction(target="light-01", scene="colonization_dark", state="off"),
        cooldown_seconds=1800,
        log_to_session=True,
    ),
    AutomationRule(
        name="Light Scene — Colonization Dark",
        description="Ensure lights off during colonization (profile: light_hours_on = 0)",
        priority=3,
        applies_to_phases=["substrate_colonization", "grain_colonization"],
        condition=RuleCondition(
            type=ConditionType.SCHEDULE,
            # photoperiod="off" with light_hours_on=0 is always true — the
            # window never opens for a dark phase. Same mechanism, no special case.
            schedule=ScheduleCondition(photoperiod="off"),
        ),
        action=RuleAction(target="light-01", scene="colonization_dark", state="off"),
        cooldown_seconds=3600,
        log_to_session=True,
    ),

    # ─── SPECIES-SPECIFIC RULES ─────────────────────────────────

    # Lion's Mane — Temperature Swing Scheduler
    AutomationRule(
        name="Lion's Mane Night Cool",
        description="Cool down for lion's mane temp swing requirement (night cycle 10pm-6am)",
        priority=7,
        applies_to_species=["lions_mane"],
        applies_to_phases=["primordia_induction"],
        condition=RuleCondition(
            type=ConditionType.COMPOUND,
            compound=CompoundCondition(
                op=CompoundOp.AND,
                conditions=[
                    RuleCondition(
                        type=ConditionType.SCHEDULE,
                        schedule=ScheduleCondition(time_range=("22:00", "06:00")),
                    ),
                    RuleCondition(
                        type=ConditionType.THRESHOLD,
                        threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=60),
                    ),
                ],
            ),
        ),
        action=RuleAction(target="plug-cooler", state="on", duration_sec=1800),
        cooldown_seconds=1800,
        safety_max_on_seconds=7200,
        log_to_session=True,
    ),

    # CO2 FLOOR — species that want CO2 held HIGH, not just capped.
    # This replaces two hardcoded species rules (reishi <1500, king_trumpet
    # <1000) with one profile-driven rule. Reishi antler morphology and king
    # trumpet primordia both need elevated CO2; the value now lives in the
    # profile's co2_min_ppm (see models.py), so any species that sets it gets
    # the same behaviour without a bespoke rule. Only fires when a floor is set
    # AND the reading is below it — species with co2_min_ppm=None never trigger.
    AutomationRule(
        name="CO2 Floor — Restrict FAE",
        description="Hold FAE off when CO2 drops below the species' floor for this phase",
        priority=12,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="co2_ppm",
                operator="lt",
                profile_ref="co2_min_ppm",
            ),
        ),
        action=RuleAction(target="relay-01", channel="fae", state="off"),
        cooldown_seconds=300,
        log_to_session=True,
    ),

    # Cordyceps — Blue light enforcement
    AutomationRule(
        name="Cordyceps Blue Light",
        description="Enforce blue-only lighting for cordyceps militaris fruiting",
        priority=7,
        applies_to_species=["cordyceps_militaris"],
        applies_to_phases=["primordia_induction", "fruiting"],
        condition=RuleCondition(
            type=ConditionType.SCHEDULE,
            schedule=ScheduleCondition(interval_min=60),
        ),
        action=RuleAction(target="light-01", scene="cordyceps_blue"),
        cooldown_seconds=3600,
        log_to_session=True,
    ),

    # ─── Weather-Aware Rules ────────────────────────────────────
    AutomationRule(
        name="Pre-cool for Hot Forecast",
        description="Activate cooler when today's forecast high exceeds 90°F to preempt closet warming",
        priority=11,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="forecast_high_f",
                operator="gt",
                value=90.0,
            ),
        ),
        action=RuleAction(target="plug-cooler", state="on", duration_sec=900),
        cooldown_seconds=1800,
        notification=True,
        log_to_session=True,
    ),

    AutomationRule(
        name="Dry Weather Humidity Boost",
        description="Increase humidifier when outdoor humidity drops below 25% (dry air infiltrates closet)",
        priority=8,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="outdoor_humidity",
                operator="lt",
                value=25.0,
            ),
        ),
        action=RuleAction(target="plug-humidifier", state="on", duration_sec=600),
        cooldown_seconds=600,
        log_to_session=True,
    ),

    AutomationRule(
        name="Heat Wave Warning",
        description="Send alert when forecast high exceeds 95°F — may not maintain cold-fruiting species targets",
        priority=15,
        enabled=True,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="forecast_high_f",
                operator="gt",
                value=95.0,
            ),
        ),
        action=RuleAction(target="plug-cooler", state="on", duration_sec=1800),
        cooldown_seconds=3600,
        notification=True,
        log_to_session=True,
    ),
]
