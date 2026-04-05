import time
from unittest.mock import patch

from app.automation.engine import (
    _eval_threshold,
    _eval_schedule,
    _evaluate_condition,
    set_override,
    get_overrides,
    is_overridden,
)
from app.automation.models import (
    ThresholdCondition,
    ScheduleCondition,
    RuleCondition,
    CompoundCondition,
    ConditionType,
    CompoundOp,
    ManualOverride,
)
from app.species.models import PhaseParams


def _phase_params(**overrides):
    defaults = dict(
        temp_min_f=72, temp_max_f=76, humidity_min=85, humidity_max=92,
        co2_max_ppm=800, co2_tolerance="low", light_hours_on=12,
        light_hours_off=12, light_spectrum="daylight_6500k", fae_mode="scheduled",
        expected_duration_days=(7, 14),
    )
    defaults.update(overrides)
    return PhaseParams(**defaults)


# ── Threshold tests ─────────────────────────────────────────────


def test_threshold_gt():
    t = ThresholdCondition(sensor="temp_f", operator="gt", value=75)
    assert _eval_threshold(t, {"temp_f": 80}, None) is True
    assert _eval_threshold(t, {"temp_f": 70}, None) is False


def test_threshold_lt():
    t = ThresholdCondition(sensor="temp_f", operator="lt", value=75)
    assert _eval_threshold(t, {"temp_f": 70}, None) is True
    assert _eval_threshold(t, {"temp_f": 80}, None) is False


def test_threshold_gte():
    t = ThresholdCondition(sensor="temp_f", operator="gte", value=75)
    assert _eval_threshold(t, {"temp_f": 75}, None) is True
    assert _eval_threshold(t, {"temp_f": 74.9}, None) is False


def test_threshold_lte():
    t = ThresholdCondition(sensor="temp_f", operator="lte", value=75)
    assert _eval_threshold(t, {"temp_f": 75}, None) is True
    assert _eval_threshold(t, {"temp_f": 75.1}, None) is False


def test_threshold_eq():
    t = ThresholdCondition(sensor="temp_f", operator="eq", value=75)
    assert _eval_threshold(t, {"temp_f": 75.05}, None) is True  # within 0.1 tolerance


def test_threshold_eq_outside_tolerance():
    t = ThresholdCondition(sensor="temp_f", operator="eq", value=75)
    assert _eval_threshold(t, {"temp_f": 75.2}, None) is False


def test_threshold_missing_sensor():
    t = ThresholdCondition(sensor="co2_ppm", operator="gt", value=800)
    assert _eval_threshold(t, {"temp_f": 75}, None) is False


def test_threshold_profile_ref():
    t = ThresholdCondition(sensor="humidity", operator="lt", profile_ref="humidity_min")
    params = _phase_params(humidity_min=85)
    assert _eval_threshold(t, {"humidity": 80}, params) is True
    assert _eval_threshold(t, {"humidity": 90}, params) is False


def test_threshold_profile_ref_missing_attr():
    t = ThresholdCondition(sensor="humidity", operator="lt", profile_ref="nonexistent")
    params = _phase_params()
    assert _eval_threshold(t, {"humidity": 80}, params) is False


def test_threshold_no_value_no_ref():
    t = ThresholdCondition(sensor="humidity", operator="lt")
    assert _eval_threshold(t, {"humidity": 80}, None) is False


# ── Schedule tests ──────────────────────────────────────────────


def _mock_localtime(hour, minute):
    """Create a struct_time-like for the given hour and minute."""
    return time.struct_time((2026, 1, 1, hour, minute, 0, 0, 1, 0))


def test_schedule_interval_match():
    s = ScheduleCondition(interval_min=20)
    with patch("app.automation.engine.time") as mock_time:
        mock_time.localtime.return_value = _mock_localtime(2, 0)  # 120 min, 120 % 20 == 0
        assert _eval_schedule(s) is True


def test_schedule_interval_no_match():
    s = ScheduleCondition(interval_min=20)
    with patch("app.automation.engine.time") as mock_time:
        mock_time.localtime.return_value = _mock_localtime(2, 5)  # 125 min, 125 % 20 != 0
        assert _eval_schedule(s) is False


def test_schedule_time_range_inside():
    s = ScheduleCondition(time_range=("08:00", "20:00"))
    with patch("app.automation.engine.time") as mock_time:
        mock_time.localtime.return_value = _mock_localtime(12, 0)
        assert _eval_schedule(s) is True


def test_schedule_time_range_outside():
    s = ScheduleCondition(time_range=("08:00", "20:00"))
    with patch("app.automation.engine.time") as mock_time:
        mock_time.localtime.return_value = _mock_localtime(22, 0)
        assert _eval_schedule(s) is False


def test_schedule_time_range_overnight_inside():
    s = ScheduleCondition(time_range=("22:00", "06:00"))
    with patch("app.automation.engine.time") as mock_time:
        mock_time.localtime.return_value = _mock_localtime(23, 0)
        assert _eval_schedule(s) is True
        mock_time.localtime.return_value = _mock_localtime(2, 0)
        assert _eval_schedule(s) is True


def test_schedule_time_range_overnight_outside():
    s = ScheduleCondition(time_range=("22:00", "06:00"))
    with patch("app.automation.engine.time") as mock_time:
        mock_time.localtime.return_value = _mock_localtime(12, 0)
        assert _eval_schedule(s) is False


def test_schedule_none():
    assert _eval_schedule(None) is False


# ── Compound condition tests ────────────────────────────────────


def test_compound_and_all_true():
    c = RuleCondition(
        type=ConditionType.COMPOUND,
        compound=CompoundCondition(
            op=CompoundOp.AND,
            conditions=[
                RuleCondition(type=ConditionType.THRESHOLD, threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=70)),
                RuleCondition(type=ConditionType.THRESHOLD, threshold=ThresholdCondition(sensor="humidity", operator="gt", value=80)),
            ],
        ),
    )
    assert _evaluate_condition(c, {"temp_f": 75, "humidity": 85}, None) is True


def test_compound_and_one_false():
    c = RuleCondition(
        type=ConditionType.COMPOUND,
        compound=CompoundCondition(
            op=CompoundOp.AND,
            conditions=[
                RuleCondition(type=ConditionType.THRESHOLD, threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=70)),
                RuleCondition(type=ConditionType.THRESHOLD, threshold=ThresholdCondition(sensor="humidity", operator="gt", value=90)),
            ],
        ),
    )
    assert _evaluate_condition(c, {"temp_f": 75, "humidity": 85}, None) is False


def test_compound_or_one_true():
    c = RuleCondition(
        type=ConditionType.COMPOUND,
        compound=CompoundCondition(
            op=CompoundOp.OR,
            conditions=[
                RuleCondition(type=ConditionType.THRESHOLD, threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=80)),
                RuleCondition(type=ConditionType.THRESHOLD, threshold=ThresholdCondition(sensor="humidity", operator="gt", value=80)),
            ],
        ),
    )
    assert _evaluate_condition(c, {"temp_f": 75, "humidity": 85}, None) is True


def test_compound_or_all_false():
    c = RuleCondition(
        type=ConditionType.COMPOUND,
        compound=CompoundCondition(
            op=CompoundOp.OR,
            conditions=[
                RuleCondition(type=ConditionType.THRESHOLD, threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=80)),
                RuleCondition(type=ConditionType.THRESHOLD, threshold=ThresholdCondition(sensor="humidity", operator="gt", value=90)),
            ],
        ),
    )
    assert _evaluate_condition(c, {"temp_f": 75, "humidity": 85}, None) is False


# ── Override tests ──────────────────────────────────────────────


def test_set_and_check_override():
    set_override(ManualOverride(target="relay-01", channel="fae", reason="testing"))
    assert is_overridden("relay-01", "fae") is True
    assert is_overridden("relay-01", "exhaust") is False


def test_override_wildcard_channel():
    set_override(ManualOverride(target="relay-01", channel=None, reason="all channels"))
    assert is_overridden("relay-01", "fae") is True
    assert is_overridden("relay-01", "exhaust") is True


def test_override_expiry():
    set_override(ManualOverride(target="relay-01", channel="fae", expires_at=time.time() - 10))
    assert is_overridden("relay-01", "fae") is False


def test_clear_override():
    set_override(ManualOverride(target="relay-01", channel="fae", reason="test"))
    assert is_overridden("relay-01", "fae") is True
    set_override(ManualOverride(target="relay-01", channel="fae", locked=False))
    assert is_overridden("relay-01", "fae") is False


def test_get_overrides_expires():
    set_override(ManualOverride(target="relay-01", channel="fae", expires_at=time.time() - 10))
    overrides = get_overrides()
    assert len(overrides) == 0
