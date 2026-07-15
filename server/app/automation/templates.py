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

    # ─── CO2 / FAE Control ──────────────────────────────────────
    AutomationRule(
        name="CO2 FAE Trigger",
        description="Activate FAE fan when CO2 exceeds species target maximum",
        priority=8,
        # Fruiting-side only. Colonization declares fae_mode="none" and wants CO2
        # HIGH (mycelium produces it); venting there dries the substrate and
        # starves the colony. The six sibling rules already gate by phase — this
        # one lacking it was an oversight, not a design choice. The engine's
        # fae_mode gate is the second line of defence.
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
        description="Emergency exhaust when CO2 exceeds the species' emergency band",
        priority=20,
        # Was a global hardcoded 3000 ppm with NO phase gate — the single most
        # damaging rule in the table. It fired the exhaust at full power during
        # colonization (where CO2 legitimately runs 5,000-15,000 ppm), and made
        # reishi antler morphology (induced at ~3,000 ppm) structurally
        # impossible. Now: fruiting-side only, and the threshold is the species'
        # own emergency edge (co2_max_ppm + co2_emergency_margin_ppm), so a
        # high-CO2 species is not vented out of its legitimate band. The
        # unconditional human-safety ceiling lives in the engine, not here.
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

    # Reishi — Antler CO2 Maintenance
    AutomationRule(
        name="Reishi Antler CO2 Restrict FAE",
        description="Hold FAE off below the species CO2 floor so antler morphology keeps its high CO2",
        priority=12,
        applies_to_species=["reishi"],
        applies_to_phases=["primordia_induction"],
        # The 1500-ppm floor used to be hardcoded here; it now lives on the
        # species' PhaseParams (co2_min_ppm) so the value travels with the
        # species, not the rule. profile_ref resolves it at fire time.
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="co2_ppm", operator="lt", profile_ref="co2_min_ppm"),
        ),
        action=RuleAction(target="relay-01", channel="fae", state="off"),
        cooldown_seconds=300,
        log_to_session=True,
    ),

    # King Trumpet — Elevated CO2 during primordia
    AutomationRule(
        name="King Trumpet Primordia CO2 Restrict",
        description="Hold FAE off below the species CO2 floor to keep king trumpet primordia CO2 elevated",
        priority=12,
        applies_to_species=["king_trumpet"],
        applies_to_phases=["primordia_induction"],
        # Was a hardcoded 1000-ppm floor; now resolved from the species'
        # co2_min_ppm, matching the reishi conversion above.
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="co2_ppm", operator="lt", profile_ref="co2_min_ppm"),
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

    # ─── Air Circulation ────────────────────────────────────────
    # The circulation fan ships in every Tier-2 kit and had ZERO rules — it
    # never ran. Unlike FAE it does not vent (changes no CO2), so it is safe in
    # high-CO2 phases and is NOT subject to the fae_mode gate. Cadence is
    # species-driven via the profile's circulation_interval_min/_duration_sec.
    AutomationRule(
        name="Circulation Cycle",
        description="Periodic internal air circulation — breaks up CO2 stratification and stagnant RH pockets",
        priority=4,
        applies_to_phases=["primordia_induction", "fruiting"],
        condition=RuleCondition(
            type=ConditionType.SCHEDULE,
            schedule=ScheduleCondition(
                profile_interval_ref="circulation_interval_min", interval_min=30,
            ),
        ),
        action=RuleAction(
            target="relay-01", channel="circulation", state="on", pwm=140,
            duration_profile_ref="circulation_duration_sec", duration_sec=120,
        ),
        cooldown_seconds=300,
        safety_max_on_seconds=1800,
        log_to_session=True,
    ),

    # ─── Humidity Removal (capability-aware) ────────────────────
    # Humidity control was one-directional (Boost/Cut only add moisture or stop
    # adding it). Nothing ever REMOVED humidity — a contamination risk in a
    # chamber pinned at 95% RH. Two rules cover it by capability:
    #   Tier 3 (dehumidifier plug present) → run the dehumidifier.
    #   Tier 2 (no dehumidifier, fans present) → vent moist air with exhaust.
    # requires_present / requires_absent make exactly one of them live, so they
    # never fight (venting also sheds CO2/temp; prefer the dehumidifier).
    AutomationRule(
        name="Dehumidifier On",
        description="Run the dehumidifier when humidity exceeds the species maximum (Tier 3 hardware)",
        priority=10,
        requires_present=["plug-dehumidifier"],
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="gt", profile_ref="humidity_max"),
        ),
        action=RuleAction(target="plug-dehumidifier", state="on", duration_sec=600),
        cooldown_seconds=120,
        safety_max_on_seconds=1800,
        log_to_session=True,
    ),
    AutomationRule(
        name="Dehumidifier Off",
        description="Stop the dehumidifier once humidity falls back to the species maximum",
        priority=10,
        requires_present=["plug-dehumidifier"],
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="lte", profile_ref="humidity_max"),
        ),
        action=RuleAction(target="plug-dehumidifier", state="off"),
        cooldown_seconds=60,
        log_to_session=False,
    ),
    AutomationRule(
        name="High Humidity Fan Evacuation",
        description="Fallback dehumidification: vent moist chamber air with the exhaust fan when no dehumidifier is present",
        priority=9,
        # Fruiting-side only. During a high-CO2 phase (fae_mode='none') the
        # engine suppresses this automatically — venting to shed RH would also
        # vent the CO2 the species needs, so we prefer the dehumidifier there
        # and fall back to an alert. requires_absent means a Tier-3 owner never
        # runs this in parallel with their dehumidifier.
        applies_to_phases=["primordia_induction", "fruiting"],
        requires_absent=["plug-dehumidifier"],
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="gt", profile_ref="humidity_max"),
        ),
        action=RuleAction(target="relay-01", channel="exhaust", state="on", pwm=220, duration_sec=180),
        cooldown_seconds=600,
        safety_max_on_seconds=900,
        log_to_session=True,
    ),

    # ─── Misting Pump (aux) — INTENTIONALLY DISABLED ────────────
    # Tier 3's peristaltic pump on relay channel `aux` (GPIO 14). It ships with
    # a ready template but is DISABLED by default: there is no defensible fully
    # automatic trigger. Over-misting is a leading cause of bacterial blotch and
    # contamination, and the humidity sensor does not measure substrate-surface
    # moisture (the thing misting actually changes). Left for the operator to
    # enable and tune per substrate. When enabled it is deliberately conservative
    # — a short pulse, a long cooldown, and a hard auto-off — but the decision to
    # run it at all is the grower's, not a guessed setpoint. (This models the
    # capability so the pump is reachable and documented, without firing blind.)
    AutomationRule(
        name="Misting Pulse (manual-enable)",
        description="Conservative substrate-surface misting pulse on low humidity — DISABLED by default (over-misting → blotch); enable and tune per substrate",
        priority=2,
        enabled=False,
        applies_to_phases=["fruiting"],
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="lt", profile_ref="humidity_min"),
        ),
        action=RuleAction(target="relay-01", channel="aux", state="on", duration_sec=8),
        cooldown_seconds=3600,
        safety_max_on_seconds=15,
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
