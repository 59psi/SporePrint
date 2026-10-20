"""Schedule conditions: cron, the species photoperiod, intervals, time ranges.

What this pins, each once a silent failure:

1. `cron` was a declared, documented field that nothing read: every cron rule
   fell through to False and never fired. It is a real 5-field cron now, and
   a minute that falls between two telemetry frames still counts.
2. The species photoperiod (light_hours_on per phase) was written and never
   read: fruiting lights ran 24/7 and the dark period did not exist.
3. FAE period/duration were hardcoded (20 min / 300 s) though every profile
   gives fae_interval_min per phase.
4. Interval schedules were wall-clock modulo (`(h*60+m) % n == 0`), matching
   only when a frame landed on an exact minute: one late frame skipped the
   cycle. "Every 20 minutes" now means 20 minutes since the rule last fired.
"""

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.automation.engine import _eval_schedule
from app.automation.models import ScheduleCondition
from tests._pi_a_engine import clock, local


def _phase(**kw):
    """A stand-in for species PhaseParams: only the fields schedules read."""
    return SimpleNamespace(
        light_hours_on=kw.get("light_hours_on", 12),
        fae_interval_min=kw.get("fae_interval_min", 20),
        fae_duration_sec=kw.get("fae_duration_sec", 300),
    )


def _at(year, month, day, hour, minute=0):
    """Freeze localtime at a local date and time."""
    st = time.localtime(time.mktime((year, month, day, hour, minute, 0, 0, 0, -1)))
    return patch("app.automation.engine.time.localtime", return_value=st)


# 2026-07-13 is a Monday, 2026-07-19 a Sunday.
_MON, _SUN = (2026, 7, 13), (2026, 7, 19)


# ── cron ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("expr,when,expected", [
    ("*/20 * * * *", (*_MON, 9, 20), True),
    ("*/20 * * * *", (*_MON, 9, 21), False),
    ("30 6 * * *", (*_MON, 6, 30), True),
    ("30 6 * * *", (*_MON, 7, 30), False),
    ("15 8-10 * * 1-5", (*_MON, 9, 15), True),
    ("0,15,30 * * * *", (*_MON, 9, 15), True),
    ("15 9 * * 0", (*_MON, 9, 15), False),
    ("15 9 * * 0", (*_SUN, 9, 15), True),     # day-of-week 0 is Sunday ...
    ("15 9 * * 7", (*_SUN, 9, 15), True),     # ... and so is 7
    # Both day fields restricted: either day matches (POSIX / Vixie cron).
    ("0 8 1 * 1", (2026, 10, 5, 8), True),    # a Monday, the 5th
    ("0 8 1 * 1", (2026, 10, 1, 8), True),    # a Thursday, the 1st
    ("0 8 1 * 1", (2026, 10, 6, 8), False),   # a Tuesday, the 6th
    # A day field starting with "*" (even "*/2") is unrestricted: both must match.
    ("0 8 */2 * 1", (2026, 10, 12, 8), True),   # Monday, even day
    ("0 8 */2 * 1", (2026, 10, 5, 8), False),   # Monday, odd day
    ("0 8 */2 * 1", (2026, 10, 6, 8), False),   # even day, Tuesday
    # A cron that cannot be read never fires.
    ("not a cron", (*_MON, 9, 20), False),
    ("*/0 * * * *", (*_MON, 9, 20), False),
    ("*/x * * * *", (*_MON, 9, 20), False),
    ("1-x * * * *", (*_MON, 9, 20), False),
    ("x * * * *", (*_MON, 9, 20), False),
])
def test_a_cron_schedule_matches_its_minute(expr, when, expected):
    with _at(*when):
        assert _eval_schedule(ScheduleCondition(cron=expr)) is expected


def test_a_cron_matches_a_minute_between_two_frames():
    """With the time the rule was last evaluated, a matching minute that
    started since then counts, and is never counted twice."""
    sched = ScheduleCondition(cron="*/20 * * * *")
    with clock(local(12, 21, 0.3)):
        assert _eval_schedule(sched, None, None, cron_since=local(12, 19, 59.6)) is True
        assert _eval_schedule(sched, None, None, cron_since=local(12, 20, 5)) is False
        assert _eval_schedule(ScheduleCondition(cron="*/20 * *"), None, None,
                              cron_since=local(12, 19)) is False


# ── species-driven photoperiod ──────────────────────────────────────────


@pytest.mark.parametrize("photoperiod,start,hours_on,hhmm,expected", [
    # 12/12 from 06:00: lit 06:00-18:00.
    ("on", "06:00", 12, (12, 0), True),
    ("on", "06:00", 12, (22, 0), False),
    ("on", "06:00", 12, (5, 59), False),
    ("on", "06:00", 12, (6, 0), True),
    ("on", "06:00", 12, (18, 0), False),
    ("off", "06:00", 12, (12, 0), False),
    ("off", "06:00", 12, (22, 0), True),
    # The same rule follows the species: 16/8 is still lit at 20:00.
    ("on", "06:00", 16, (20, 0), True),
    ("on", "06:00", 12, (20, 0), False),
    # A dark phase (colonization) never opens the window; continuous light
    # never closes it.
    ("on", "06:00", 0, (12, 0), False),
    ("off", "06:00", 0, (12, 0), True),
    ("on", "06:00", 24, (3, 0), True),
    ("off", "06:00", 24, (3, 0), False),
    # A window that wraps past midnight: 20:00 → 08:00.
    ("on", "20:00", 12, (23, 0), True),
    ("on", "20:00", 12, (2, 0), True),
    ("on", "20:00", 12, (9, 0), False),
    # Read in any case and spacing.
    (" ON ", "06:00", 12, (12, 0), True),
    (" ON ", "06:00", 12, (22, 0), False),
    # A start it cannot read opens the window at 06:00.
    ("on", "noon", 12, (7, 0), True),
    ("on", "noon", 12, (5, 0), False),
    # Anything but on/off never matches: it used to read as "off" and ran
    # the rule through the dark period (and all day in a dark phase).
    ("bogus", "06:00", 0, (3, 0), False),
    ("bogus", "06:00", 12, (12, 0), False),
    ("bogus", "06:00", 12, (22, 0), False),
    ("bogus", "06:00", 24, (22, 0), False),
])
def test_the_photoperiod_follows_the_species_light_window(photoperiod, start, hours_on,
                                                         hhmm, expected):
    sched = ScheduleCondition(photoperiod=photoperiod, photoperiod_start=start)
    with _at(*_MON, *hhmm):
        assert _eval_schedule(sched, _phase(light_hours_on=hours_on)) is expected


def test_a_photoperiod_with_no_light_hours_never_fires():
    """No profile, or one with no light hours: never guess a light cycle."""
    on = ScheduleCondition(photoperiod="on")
    off = ScheduleCondition(photoperiod="off")
    with _at(*_MON, 12):
        assert _eval_schedule(on, None) is False
        assert _eval_schedule(on, SimpleNamespace()) is False
        assert _eval_schedule(off, SimpleNamespace()) is False


# ── intervals: species-driven, elapsed since the last fire ──────────────


@pytest.mark.parametrize("sched,phase,minutes_ago,expected", [
    (ScheduleCondition(interval_min=20), None, 21, True),
    (ScheduleCondition(interval_min=20), None, 3, False),
    (ScheduleCondition(interval_min=20), None, None, True),   # never fired: fires now
    # The species' period wins over the rule's literal: 25 min is due under
    # the literal 20, not under the species' 30.
    (ScheduleCondition(profile_interval_ref="fae_interval_min", interval_min=20),
     _phase(fae_interval_min=30), 25, False),
    (ScheduleCondition(profile_interval_ref="fae_interval_min", interval_min=20),
     _phase(fae_interval_min=30), 31, True),
    # A profile silent on the period falls back to the literal.
    (ScheduleCondition(profile_interval_ref="fae_interval_min", interval_min=20),
     SimpleNamespace(), 21, True),
    (ScheduleCondition(profile_interval_ref="fae_interval_min", interval_min=20),
     SimpleNamespace(), 5, False),
])
def test_an_interval_counts_from_the_last_fire_not_the_wall_clock(sched, phase, minutes_ago,
                                                                  expected):
    last_fired = None if minutes_ago is None else time.time() - minutes_ago * 60
    with _at(*_MON, 9, 7):  # not a multiple of 20: the old modulo form never matched here
        assert _eval_schedule(sched, phase, last_fired=last_fired) is expected


# ── time ranges ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("time_range,hhmm,expected", [
    (("08:00", "20:00"), (12, 0), True),
    (("08:00", "20:00"), (8, 0), True),      # the start is in the range ...
    (("08:00", "20:00"), (20, 0), False),    # ... the end is not
    (("08:00", "20:00"), (22, 0), False),
    (("22:00", "06:00"), (23, 0), True),     # overnight
    (("22:00", "06:00"), (2, 0), True),
    (("22:00", "06:00"), (6, 0), False),
    (("22:00", "06:00"), (12, 0), False),
])
def test_a_time_range_matches_inside_it(time_range, hhmm, expected):
    with _at(*_MON, *hhmm):
        assert _eval_schedule(ScheduleCondition(time_range=time_range)) is expected


def test_a_schedule_that_says_nothing_never_fires():
    with _at(*_MON, 12):
        assert _eval_schedule(None) is False
        assert _eval_schedule(ScheduleCondition()) is False
