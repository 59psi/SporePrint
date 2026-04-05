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
        description="Emergency exhaust activation when CO2 exceeds 3000ppm",
        priority=20,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(
                sensor="co2_ppm",
                operator="gt",
                value=3000,
            ),
        ),
        action=RuleAction(target="relay-01", channel="exhaust", state="on", pwm=255, duration_sec=600),
        cooldown_seconds=120,
        notification=True,
        log_to_session=True,
    ),
    AutomationRule(
        name="Scheduled FAE Cycle",
        description="Periodic FAE fan activation every 20 minutes during fruiting phases",
        priority=5,
        applies_to_phases=["primordia_induction", "fruiting"],
        condition=RuleCondition(
            type=ConditionType.SCHEDULE,
            schedule=ScheduleCondition(interval_min=20),
        ),
        action=RuleAction(target="relay-01", channel="fae", state="on", pwm=180, duration_sec=300),
        cooldown_seconds=1200,
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

    # ─── Light Sync ─────────────────────────────────────────────
    AutomationRule(
        name="Light Scene — Fruiting",
        description="Switch to fruiting light scene when entering fruiting phase",
        priority=3,
        applies_to_phases=["fruiting"],
        condition=RuleCondition(
            type=ConditionType.SCHEDULE,
            schedule=ScheduleCondition(interval_min=60),
        ),
        action=RuleAction(target="light-01", scene="fruiting_standard"),
        cooldown_seconds=3600,
        log_to_session=True,
    ),
    AutomationRule(
        name="Light Scene — Colonization Dark",
        description="Ensure lights off during colonization",
        priority=3,
        applies_to_phases=["substrate_colonization", "grain_colonization"],
        condition=RuleCondition(
            type=ConditionType.SCHEDULE,
            schedule=ScheduleCondition(interval_min=60),
        ),
        action=RuleAction(target="light-01", scene="colonization_dark"),
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
        description="Keep FAE minimal during reishi antler formation to maintain high CO2 >1500ppm",
        priority=12,
        applies_to_species=["reishi"],
        applies_to_phases=["primordia_induction"],
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="co2_ppm", operator="lt", value=1500),
        ),
        action=RuleAction(target="relay-01", channel="fae", state="off"),
        cooldown_seconds=300,
        log_to_session=True,
    ),

    # King Trumpet — Elevated CO2 during primordia
    AutomationRule(
        name="King Trumpet Primordia CO2 Restrict",
        description="Restrict FAE during king trumpet primordia to keep CO2 elevated (1000-2000ppm)",
        priority=12,
        applies_to_species=["king_trumpet"],
        applies_to_phases=["primordia_induction"],
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="co2_ppm", operator="lt", value=1000),
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
]
