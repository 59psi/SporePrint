"""Cloud manual actuator override — the relay-path twin of the Pi's LAN
POST/DELETE /api/automation/overrides (closes the cloud→Pi override half).

The cloud's POST /devices/{id}/actuator emits TWO frames per manual toggle: the
raw relay command (already handled Pi-side → MQTT publish) AND an
`automation`/`override` command so the rules engine doesn't re-flip the manual
change on its next tick. Before this fix the Pi rejected the second frame
outright (`automation` wasn't an accepted target_kind), so a manual cloud toggle
lived only until the next telemetry tick, then automation clawed it back.

These pin the Pi-side handling of that second frame:
  - set     → an expiring ManualOverride on the actuator's node/channel;
  - release → the override is cleared and automation resumes control.

Driven through the importable `_dispatch_automation_command` seam — the same
seam test_automation_remote_hold.py uses for the `system` dispatcher.
"""

import json
import time

from app.automation.engine import get_overrides, is_overridden
from app.automation.models import MAX_OVERRIDE_TTL_SECONDS
from app.cloud.service import _dispatch_automation_command
from app.db import get_db


async def _register_node(node_id: str, node_type: str) -> None:
    """Register a firmware-v2 node so _resolve_node_id_by_type finds it."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, roles, last_seen) "
            "VALUES (?, ?, ?, ?)",
            (node_id, node_type, json.dumps([node_type]), time.time()),
        )
        await db.commit()


# ── set registers an expiring override ─────────────────────────────────────


async def test_override_set_registers_expiring_override():
    """A cloud 'set' pins the fan's relay channel out of automation's reach,
    with an expiry — not a sticky-forever hold."""
    await _register_node("relay-01", "relay")

    before = time.time()
    duration = 600  # 10 min — the cloud's duration_sec
    ok, err = await _dispatch_automation_command(
        "override",
        {"channel": "fae", "state": "on", "duration_sec": duration,
         "expires_at": before + duration},
    )
    assert ok is True and err is None

    # fae maps to the relay node; that (node, channel) is now overridden…
    assert is_overridden("relay-01", "fae") is True
    ov = next(o for o in await get_overrides()
              if o.target == "relay-01" and o.channel == "fae")
    # …locked, and EXPIRING ~10 min out.
    assert ov.locked is True
    assert ov.expires_at is not None
    assert 9.5 * 60 <= (ov.expires_at - before) <= 10.5 * 60


async def test_override_set_falls_back_to_duration_when_no_expires_at():
    """No absolute expires_at → the Pi derives one from duration_sec."""
    await _register_node("relay-01", "relay")
    before = time.time()
    ok, err = await _dispatch_automation_command(
        "override", {"channel": "aux", "state": "on", "duration_sec": 300},
    )
    assert ok is True and err is None
    ov = next(o for o in await get_overrides() if o.channel == "aux")
    assert ov.expires_at is not None
    assert 4.5 * 60 <= (ov.expires_at - before) <= 5.5 * 60


async def test_override_set_light_maps_to_lighting_node():
    """white is a lighting-bank channel → the override targets the lighting node
    (what a light rule's action targets), not the relay node."""
    await _register_node("light-01", "lighting")
    ok, err = await _dispatch_automation_command(
        "override",
        {"channel": "white", "state": "on", "duration_sec": 300,
         "expires_at": time.time() + 300},
    )
    assert ok is True and err is None
    assert is_overridden("light-01", "white") is True


# ── release clears the override ────────────────────────────────────────────


async def test_override_release_clears_override():
    """A cloud 'release' clears the hold so automation resumes control."""
    await _register_node("relay-01", "relay")

    # Pre-existing hold from a prior 'set'.
    ok, _ = await _dispatch_automation_command(
        "override",
        {"channel": "aux", "state": "on", "duration_sec": 600,
         "expires_at": time.time() + 600},
    )
    assert ok is True
    assert is_overridden("relay-01", "aux") is True

    ok, err = await _dispatch_automation_command(
        "override", {"channel": "aux", "release": True},
    )
    assert ok is True and err is None
    assert is_overridden("relay-01", "aux") is False
    assert not any(o.target == "relay-01" and o.channel == "aux"
                   for o in await get_overrides())


# ── honest degradation, never a crash ──────────────────────────────────────


async def test_override_absurd_expiry_is_clamped_to_ttl_ceiling():
    """A cloud expires_at past the Pi's ceiling is clamped, not honoured — a
    fat-fingered duration can't pin the actuator off for a year."""
    await _register_node("relay-01", "relay")
    before = time.time()
    ten_years = before + 10 * 365 * 24 * 60 * 60
    ok, _ = await _dispatch_automation_command(
        "override", {"channel": "fae", "state": "on", "expires_at": ten_years},
    )
    assert ok is True
    ov = next(o for o in await get_overrides() if o.channel == "fae")
    assert ov.expires_at is not None
    assert ov.expires_at <= before + MAX_OVERRIDE_TTL_SECONDS + 1


async def test_override_unmappable_channel_is_honest_noop():
    """A smart-plug/unknown channel (heater/pump → no relay/lighting node) must
    not crash and must not silently claim success."""
    ok, err = await _dispatch_automation_command(
        "override", {"channel": "heater", "state": "on", "duration_sec": 600},
    )
    assert ok is False
    assert err and "heater" in err
    assert await get_overrides() == []


async def test_override_no_registered_node_is_honest_noop():
    """A mappable channel but no relay node registered → honest no-op."""
    ok, err = await _dispatch_automation_command(
        "override", {"channel": "fae", "release": True},
    )
    assert ok is False
    assert err and "relay" in err


async def test_override_missing_channel_rejected():
    ok, err = await _dispatch_automation_command("override", {"state": "on"})
    assert ok is False
    assert err and "channel" in err


async def test_unknown_automation_channel_rejected():
    ok, err = await _dispatch_automation_command("bogus", {"channel": "fae"})
    assert ok is False
    assert err and "bogus" in err
