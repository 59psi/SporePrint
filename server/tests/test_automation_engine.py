"""How a rule's condition reads one telemetry frame: thresholds and compounds.

A condition is three-valued: True, False, or None when the frame cannot say
(the sensor it compares is missing or not a finite number). A relay or
lighting node's frame carries no climate readings at all, and that is not the
condition going false: a rule in force keeps its actuator through such a
frame (see test_automation_actuators.py). Only True fires a rule.

Schedules: tests/test_automation_scheduling.py. Manual holds:
tests/test_automation_holds_and_ceilings.py.
"""

import pytest

from app.automation.engine import _condition_state, _eval_threshold, _evaluate_condition
from app.automation.models import CompoundCondition, CompoundOp, ConditionType, RuleCondition
from app.species.models import PhaseParams
from tests._builders import threshold

PHASE = PhaseParams(
    temp_min_f=72, temp_max_f=76, humidity_min=85, humidity_max=92,
    co2_max_ppm=800, co2_tolerance="low", light_hours_on=12,
    light_hours_off=12, light_spectrum="daylight_6500k", fae_mode="scheduled",
    expected_duration_days=(7, 14),
)


@pytest.mark.parametrize("operator,value,reading,expected", [
    ("gt", 75, 80, True), ("gt", 75, 75, False), ("gt", 75, 70, False),
    ("lt", 75, 70, True), ("lt", 75, 80, False),
    ("gte", 75, 75, True), ("gte", 75, 74.9, False),
    ("lte", 75, 75, True), ("lte", 75, 75.1, False),
    ("eq", 75, 75.05, True), ("eq", 75, 75.2, False),   # equal within 0.1
    # A boolean reading (door_open) compares as 0 / 1, as history stores it.
    ("gt", 0.5, True, True), ("gt", 0.5, False, False),
    # No usable reading: unknown, never a match. The firmware writes a NaN
    # dew point as null; comparing a null or a string raised and skipped the
    # rule on every frame.
    ("gt", 75, None, None), ("gt", 75, float("nan"), None), ("gt", 75, "80", None),
])
def test_a_threshold_compares_the_reading_to_its_value(operator, value, reading, expected):
    cond = threshold("temp_f", operator, value)
    assert _condition_state(cond, {"temp_f": reading}) is expected
    assert _eval_threshold(cond.threshold, {"temp_f": reading}) is (expected is True)


def test_a_missing_sensor_is_unknown_not_false():
    assert _condition_state(threshold("co2_ppm", "gt", 800), {"temp_f": 75}) is None


@pytest.mark.parametrize("ref,reading,params,expected", [
    ("humidity_min", 80, PHASE, True),
    ("humidity_min", 90, PHASE, False),
    # A profile field the phase does not set (co2_min_ppm: a species with no
    # CO2 floor) or does not have never matches.
    ("co2_min_ppm", 80, PHASE, False),
    ("nonexistent", 80, PHASE, False),
    # No active phase, or no value and no profile_ref: nothing to compare to.
    ("humidity_min", 80, None, False),
    (None, 80, PHASE, False),
])
def test_a_profile_threshold_reads_the_active_phase(ref, reading, params, expected):
    cond = threshold("humidity", "lt", profile_ref=ref)
    assert _condition_state(cond, {"humidity": reading}, params) is expected


# Branches: T holds on the frame, F does not, U cannot be judged (no CO2 reading).
_T = threshold("temp_f", "gt", 70)
_F = threshold("humidity", "gt", 90)
_U = threshold("co2_ppm", "gt", 1)
_FRAME = {"temp_f": 75, "humidity": 85}


@pytest.mark.parametrize("op,branches,expected", [
    (CompoundOp.AND, [_T, _T], True),
    (CompoundOp.AND, [_T, _F], False),
    (CompoundOp.AND, [_F, _U], False),   # one false branch settles an AND
    (CompoundOp.AND, [_T, _U], None),
    (CompoundOp.OR, [_F, _T], True),
    (CompoundOp.OR, [_U, _T], True),     # one true branch settles an OR
    (CompoundOp.OR, [_F, _F], False),
    (CompoundOp.OR, [_F, _U], None),
])
def test_a_compound_condition_is_three_valued(op, branches, expected):
    cond = RuleCondition(type=ConditionType.COMPOUND,
                         compound=CompoundCondition(op=op, conditions=branches))
    assert _condition_state(cond, _FRAME) is expected
    assert _evaluate_condition(cond, _FRAME) is (expected is True)
