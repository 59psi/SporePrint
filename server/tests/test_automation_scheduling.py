"""The schedule must be driven by the species profile, and cron must work.

Three silent failures this pins:

1. `cron` was a declared, documented field that NOTHING read — `_eval_schedule`
   handled only interval_min and time_range, so any cron rule fell through to
   `return False` and never fired.

2. The species photoperiod was written and never read. Every profile specifies
   light_hours_on / light_hours_off per phase; the seeded light rules just
   re-asserted a fixed scene every 60 minutes. Fruiting lights ran 24/7 and the
   dark period didn't exist. For mushrooms the photoperiod is a fruiting
   trigger, not decoration.

3. FAE period/duration were hardcoded (20 min / 300 s) while every profile
   specifies fae_interval_min and fae_duration_sec per phase — so a species
   asking for 30-minute cycles got 20.

Plus: interval schedules were wall-clock modulo (`(h*60+m) % n == 0`), which
only matched when an evaluation landed exactly on a matching minute. Rules are
evaluated on telemetry arrival (~60 s, and it drifts), so one late frame skipped
the cycle entirely and the fan never ran that round.
"""

import time
from types import SimpleNamespace
from unittest.mock import patch

from app.automation.engine import _eval_schedule
from app.automation.models import ScheduleCondition


def _phase(**kw):
    """A stand-in for species PhaseParams — only the fields schedules read."""
    return SimpleNamespace(
        light_hours_on=kw.get("light_hours_on", 12),
        fae_interval_min=kw.get("fae_interval_min", 20),
        fae_duration_sec=kw.get("fae_duration_sec", 300),
    )


def _at(hour, minute=0, wday=0):
    """Freeze localtime at a given clock time (Monday by default)."""
    st = time.struct_time((2026, 7, 13, hour, minute, 0, wday, 194, 0))
    return patch("app.automation.engine.time.localtime", return_value=st)


# ── cron ────────────────────────────────────────────────────────────────


def test_cron_every_20_minutes():
    sched = ScheduleCondition(cron="*/20 * * * *")
    with _at(9, 20):
        assert _eval_schedule(sched) is True
    with _at(9, 21):
        assert _eval_schedule(sched) is False


def test_cron_specific_hour_and_minute():
    sched = ScheduleCondition(cron="30 6 * * *")   # 06:30 daily
    with _at(6, 30):
        assert _eval_schedule(sched) is True
    with _at(7, 30):
        assert _eval_schedule(sched) is False


def test_cron_ranges_lists_and_dow():
    with _at(9, 15, wday=0):  # Monday
        assert _eval_schedule(ScheduleCondition(cron="15 8-10 * * 1-5")) is True
        assert _eval_schedule(ScheduleCondition(cron="15 9 * * 0")) is False   # Sunday only
        assert _eval_schedule(ScheduleCondition(cron="0,15,30 * * * *")) is True
    with _at(9, 15, wday=6):  # Sunday — cron dow 0 AND 7
        assert _eval_schedule(ScheduleCondition(cron="15 9 * * 0")) is True
        assert _eval_schedule(ScheduleCondition(cron="15 9 * * 7")) is True


def test_malformed_cron_does_not_fire():
    assert _eval_schedule(ScheduleCondition(cron="not a cron")) is False


# ── species-driven photoperiod ──────────────────────────────────────────


def test_photoperiod_12_12_is_a_real_cycle():
    """06:00 start, 12h on → lights on 06:00-18:00, off 18:00-06:00."""
    on = ScheduleCondition(photoperiod="on", photoperiod_start="06:00")
    off = ScheduleCondition(photoperiod="off", photoperiod_start="06:00")
    phase = _phase(light_hours_on=12)

    with _at(12, 0):   # midday — inside the window
        assert _eval_schedule(on, phase) is True
        assert _eval_schedule(off, phase) is False
    with _at(22, 0):   # night — outside it
        assert _eval_schedule(on, phase) is False
        assert _eval_schedule(off, phase) is True
    with _at(5, 59):   # one minute before dawn
        assert _eval_schedule(on, phase) is False
    with _at(6, 0):    # window opens
        assert _eval_schedule(on, phase) is True
    with _at(18, 0):   # window closes
        assert _eval_schedule(on, phase) is False


def test_photoperiod_follows_the_species_not_the_rule():
    """The SAME rule yields 16/8 for a 16-hour species. That's the point."""
    on = ScheduleCondition(photoperiod="on", photoperiod_start="06:00")
    with _at(20, 0):  # 8pm
        assert _eval_schedule(on, _phase(light_hours_on=12)) is False  # 12/12 → dark
        assert _eval_schedule(on, _phase(light_hours_on=16)) is True   # 16/8  → still lit


def test_dark_phase_never_opens_the_window():
    """Colonization has light_hours_on=0 — no special-casing needed."""
    on = ScheduleCondition(photoperiod="on")
    off = ScheduleCondition(photoperiod="off")
    dark = _phase(light_hours_on=0)
    for hour in (0, 6, 12, 18):
        with _at(hour):
            assert _eval_schedule(on, dark) is False
            assert _eval_schedule(off, dark) is True


def test_continuous_light_never_closes_the_window():
    on = ScheduleCondition(photoperiod="on")
    always = _phase(light_hours_on=24)
    with _at(3, 0):
        assert _eval_schedule(on, always) is True
        assert _eval_schedule(ScheduleCondition(photoperiod="off"), always) is False


def test_photoperiod_window_wraps_past_midnight():
    """A 20:00 start with 12h on runs 20:00 → 08:00."""
    on = ScheduleCondition(photoperiod="on", photoperiod_start="20:00")
    phase = _phase(light_hours_on=12)
    with _at(23, 0):
        assert _eval_schedule(on, phase) is True
    with _at(2, 0):     # after midnight, still lit
        assert _eval_schedule(on, phase) is True
    with _at(9, 0):     # after the window closed
        assert _eval_schedule(on, phase) is False


def test_photoperiod_without_a_species_profile_does_not_fire():
    """No profile = no opinion. Never guess a light cycle."""
    assert _eval_schedule(ScheduleCondition(photoperiod="on"), None) is False


# ── species-driven interval + elapsed semantics ─────────────────────────


def test_interval_comes_from_the_species_profile():
    """profile_interval_ref wins over the literal fallback."""
    sched = ScheduleCondition(profile_interval_ref="fae_interval_min", interval_min=20)
    phase = _phase(fae_interval_min=30)
    now = time.time()

    # 25 min since last fire: due under the rule's literal 20, NOT under the
    # species' 30. The species must win.
    assert _eval_schedule(sched, phase, last_fired=now - 25 * 60) is False
    assert _eval_schedule(sched, phase, last_fired=now - 31 * 60) is True


def test_interval_falls_back_to_the_literal_when_the_profile_is_silent():
    sched = ScheduleCondition(profile_interval_ref="fae_interval_min", interval_min=20)
    phase = SimpleNamespace()  # profile with no FAE fields at all
    now = time.time()
    assert _eval_schedule(sched, phase, last_fired=now - 21 * 60) is True
    assert _eval_schedule(sched, phase, last_fired=now - 5 * 60) is False


def test_interval_is_elapsed_based_not_wall_clock_modulo():
    """The old modulo form only matched on an exact minute boundary, so a
    telemetry frame arriving a minute late skipped the whole cycle."""
    sched = ScheduleCondition(interval_min=20)
    now = time.time()
    with _at(9, 7):   # NOT a multiple of 20 — the old code returned False here
        assert _eval_schedule(sched, None, last_fired=now - 21 * 60) is True
        assert _eval_schedule(sched, None, last_fired=now - 3 * 60) is False


def test_never_fired_rule_fires_immediately():
    with _at(9, 7):
        assert _eval_schedule(ScheduleCondition(interval_min=20), None, last_fired=None) is True
