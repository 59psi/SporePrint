"""Manual holds, and how they meet safety ceilings.

The manual_overrides table is the truth and the engine's cache holds the same
one hold per actuator. A hold keeps automation from sending new commands; it
never removes a ceiling on an actuator automation already switched ON, and a
ceiling's lockout is never cut short by a shorter hold.

Which holds keep a rule off its actuator under its other names:
tests/test_automation_rule_holds.py. Holds from the cloud (pause, suspend):
tests/test_automation_remote_hold.py. A hold's window on the Pi's clock:
tests/test_override_duration.py.
"""

import asyncio
import time
from unittest.mock import patch

import pytest

import app.automation.engine as engine
from app.automation.engine import (
    _fire_rule,
    _load_overrides_from_db,
    clear_override,
    get_overrides,
    is_overridden,
    set_override,
    suspend_rule,
)
from app.automation.models import MAX_OVERRIDE_TTL_SECONDS, ManualOverride, RuleAction
from app.automation.service import create_rule
from app.db import get_db
from tests._pi_a_engine import (  # noqa: F401 (fixtures)
    REAL_SLEEP,
    alerts,
    engine_state,
    frozen_sleep,
    gated_sleep,
    make_rule,
    quiet_alerts,
    rows,
    watchdog_rows,
)


# ── one hold per actuator, in the table and the cache ──────────────────────


async def test_a_hold_keeps_automation_off_its_channel_or_its_whole_target():
    await set_override(ManualOverride(target="relay-01", channel="fae", reason="testing"))
    assert is_overridden("relay-01", "fae") is True
    assert is_overridden("relay-01", "exhaust") is False
    await set_override(ManualOverride(target="relay-02", channel=None, reason="all channels"))
    assert is_overridden("relay-02", "fae") is True
    assert is_overridden("relay-02", "exhaust") is True


async def test_a_released_hold_frees_the_actuator():
    await set_override(ManualOverride(target="relay-01", channel="fae", reason="a"))
    await set_override(ManualOverride(target="relay-01", channel="fae", locked=False))
    assert is_overridden("relay-01", "fae") is False
    await set_override(ManualOverride(target="relay-01", channel=None, reason="b"))
    await clear_override("relay-01", None)
    assert is_overridden("relay-01", "aux") is False
    assert await get_overrides() == []
    assert await rows("SELECT * FROM manual_overrides") == []


@pytest.mark.parametrize("expires_at", [time.time() - 10, 0])
async def test_an_expired_hold_is_neither_held_nor_listed(expires_at):
    """An expiry of 0 is long past, not "never" (it used to be read as falsy).
    The hot-path check drops an expired hold from the cache; the list prunes
    it from the table as well."""
    for channel in ("fae", "aux"):
        await set_override(ManualOverride(target="relay-01", channel=channel,
                                          expires_at=expires_at))
    assert is_overridden("relay-01", "fae") is False
    assert "relay-01:fae" not in engine._overrides
    assert await get_overrides() == []
    assert await rows("SELECT * FROM manual_overrides") == [], "pruned from the table too"
    assert is_overridden("relay-01", "aux") is False


async def test_override_persists_across_reload():
    """A hold survives a process restart (the table is the truth), with its
    reason and the state it pinned."""
    await set_override(ManualOverride(target="relay-01", channel="heater",
                                      reason="operator hold", held_state=" ON "))
    assert await rows("SELECT held_state FROM manual_overrides") == [{"held_state": "on"}]
    engine._overrides.clear()
    engine._overrides_loaded = False
    await engine.ensure_overrides_loaded()
    assert is_overridden("relay-01", "heater") is True
    (held,) = await get_overrides()
    assert (held.target, held.channel, held.reason, held.held_state) == (
        "relay-01", "heater", "operator hold", "on")


async def test_a_new_hold_replaces_the_one_on_the_same_actuator():
    await set_override(ManualOverride(target="node-relay", channel="fae", reason="cloud 2h",
                                      expires_at=time.time() + 7200))
    await set_override(ManualOverride(target="node-relay", channel="fae", reason="lan 1s",
                                      expires_at=time.time() + 1))
    assert [r["reason"] for r in await rows("SELECT reason FROM manual_overrides")] == ["lan 1s"]

    # Once the newer hold has run out, nothing comes back on a reload.
    later = time.time() + 5
    with patch.object(engine.time, "time", lambda: later):
        await _load_overrides_from_db()
        assert not is_overridden("node-relay", "fae")
    assert await rows("SELECT * FROM manual_overrides") == []


async def test_older_duplicate_holds_collapse_to_the_newest_at_load():
    now = time.time()
    async with get_db() as db:
        for reason, expires in (("old 2h", now + 7200), ("new 10m", now + 600)):
            await db.execute(
                "INSERT INTO manual_overrides (target, channel, locked, reason, expires_at) "
                "VALUES ('node-relay', 'fae', 1, ?, ?)", (reason, expires),
            )
        await db.commit()
    await _load_overrides_from_db()
    assert [o.reason for o in await get_overrides()] == ["new 10m"]
    assert [r["reason"] for r in await rows("SELECT reason FROM manual_overrides")] == ["new 10m"]


async def test_an_until_cancelled_hold_gets_its_ceiling_written_back():
    """Clamped in memory only, a hold with no expiry was re-clamped at every
    boot and never ended."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO manual_overrides (target, channel, locked, reason, expires_at) "
            "VALUES ('plug-heater', NULL, 1, 'forgotten', NULL)",
        )
        await db.commit()
    before = time.time()
    await _load_overrides_from_db()
    (row,) = await rows("SELECT expires_at FROM manual_overrides")
    assert row["expires_at"] == pytest.approx(before + MAX_OVERRIDE_TTL_SECONDS, abs=60)


@pytest.mark.parametrize("offset,clamped", [
    (None, True),                     # "until cancelled": a sticky-forever hold
    ("nan", True),                    # NaN compares false both ways: it never expired
    (10 * 365 * 86400.0, True),       # ten years
    (5 * 60.0, False),                # inside the ceiling: untouched
    (-10.0, False),                   # already past: several paths read it as expired
])
def test_a_hold_expiry_is_clamped_to_the_ttl_ceiling(offset, clamped):
    now = time.time()
    expires_at = {None: None, "nan": float("nan")}.get(offset) if offset in (None, "nan") \
        else now + offset
    ov = ManualOverride(target="relay-01", channel="heater", expires_at=expires_at)
    if clamped:
        assert ov.expires_at == pytest.approx(now + MAX_OVERRIDE_TTL_SECONDS, abs=5)
    else:
        assert ov.expires_at == pytest.approx(now + offset, abs=0.01)


# ── a hold never removes a ceiling, and never shortens a lockout ───────────


@pytest.mark.parametrize("hold", ["operator", "cloud rule suspend"])
async def test_a_hold_leaves_a_running_ceiling_armed(frozen_sleep, mock_mqtt, hold):
    """A hold stops automation sending NEW commands; it must not remove the
    fire-risk ceiling on a heater automation already switched ON (a 30-minute
    cloud suspend used to leave it with no cutoff at all). The ceiling keeps
    running, and its row survives a reboot."""
    rule = make_rule(RuleAction(target="relay-01", channel="heater"), ceiling=1800,
                     name="Heating Trigger", rule_id=None)
    rule.id = await create_rule(rule)
    await _fire_rule(rule, {"temp_f": 55}, None)
    armed = engine._safety_tasks["relay-01:heater"]

    if hold == "operator":
        await set_override(ManualOverride(target="relay-01", channel="heater", reason="operator"))
    else:
        await suspend_rule(rule.id, minutes=30)
    for _ in range(3):
        await REAL_SLEEP(0)

    assert is_overridden("relay-01", "heater")
    assert engine._safety_tasks.get("relay-01:heater") is armed and not armed.done()
    assert len(await watchdog_rows()) == 1


async def test_a_hold_about_to_end_does_not_cut_the_lockout_short(gated_sleep, mock_mqtt,
                                                                  quiet_alerts):
    await _fire_rule(make_rule(RuleAction(target="relay-01", channel="heater"), ceiling=60,
                               name="heat"), {}, None)
    trip = engine._safety_tasks["relay-01:heater"]
    await set_override(ManualOverride(target="relay-01", channel="heater", reason="maintenance",
                                      expires_at=time.time() + 1))
    gated_sleep.set()
    await asyncio.wait_for(asyncio.shield(trip), 2)
    later = time.time() + 5
    with patch.object(engine.time, "time", lambda: later):
        assert is_overridden("relay-01", "heater")


async def test_a_trip_under_a_longer_operator_hold_keeps_the_hold_and_says_so(
        gated_sleep, mock_mqtt, alerts):
    await _fire_rule(make_rule(RuleAction(target="relay-01", channel="heater"), ceiling=60,
                               name="heat"), {}, None)
    trip = engine._safety_tasks["relay-01:heater"]
    await set_override(ManualOverride(target="relay-01", channel="heater", reason="operator"))
    gated_sleep.set()
    await asyncio.wait_for(asyncio.shield(trip), 2)

    assert [o.reason for o in await get_overrides()] == ["operator"]
    (title, message), = alerts["warning"]
    assert title == "Safety cutoff: relay-01:heater"
    assert "hold" in message and "15 min" not in message
