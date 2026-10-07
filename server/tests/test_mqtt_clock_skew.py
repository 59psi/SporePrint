"""Telemetry liveness never depends on the Pi's clock (final review, safety).

A synced frame used to count as "not live" when its ts was more than 120 s
behind the Pi's wall clock. Such a frame was stored but skipped
evaluate_rules and _check_safety_thresholds, so no CO2 emergency exhaust and
no temperature pages. Only a DEBUG line recorded it. A Pi clock running a few
minutes fast (blocked or broken NTP on the Pi) silently stopped automation
for every node on current firmware.

Contract now:
  * A frame is not live only if it carries "replay": true, or if its ts is
    older than the newest ts already accepted live from that node (a late,
    out-of-order frame).
  * Pi-vs-node clock skew is measured per node and reported: a rate-limited
    WARNING when |skew| > 120 s, and the per-node figure in
    GET /api/health/detail/system (reliability.node_clock_skew).
"""

import logging
import time
from types import SimpleNamespace

import pytest

import app.mqtt as mqtt
from app.db import get_db
from app.mqtt import _handle_message, get_reliability_counters

NODE = "climate-01"
TOPIC = f"sporeprint/{NODE}/telemetry"


class _Sio:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.events.append((event, data))

    def named(self, event):
        return [d for e, d in self.events if e == event]


@pytest.fixture()
def forwards():
    return []


@pytest.fixture()
def rules(monkeypatch, forwards):
    calls: list[tuple[str, dict]] = []

    async def _spy(node_id, readings, sio=None):
        calls.append((node_id, dict(readings)))

    async def _forward(node_id, payload):
        forwards.append((node_id, dict(payload)))

    monkeypatch.setattr("app.automation.engine.evaluate_rules", _spy)
    monkeypatch.setattr("app.mqtt.forward_telemetry", _forward)
    monkeypatch.setattr("app.weather.service.get_current_weather", lambda: None)
    return calls


def _pi_clock(monkeypatch, offset: float) -> None:
    """Run the Pi's clock (as mqtt.py reads it) `offset` seconds off real time."""
    real = time.time
    monkeypatch.setattr(mqtt, "time", SimpleNamespace(time=lambda: real() + offset))


async def _rows(sensor: str):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT timestamp, value FROM telemetry_readings "
            "WHERE node_id = ? AND sensor = ? ORDER BY timestamp",
            (NODE, sensor),
        )
        return [dict(r) for r in await cursor.fetchall()]


# ── Pi clock ahead of the node ────────────────────────────────────────────


async def test_pi_clock_five_minutes_ahead_still_evaluates_rules(monkeypatch, rules, forwards):
    _pi_clock(monkeypatch, +300)
    sio = _Sio()
    for co2 in (4200, 4300):
        # The node is NTP-synced to real time; the Pi runs 5 minutes fast.
        await _handle_message(sio, TOPIC, {"co2_ppm": co2, "ts": time.time()})
    # Every frame reached the rules engine (and so the safety thresholds).
    assert [r["co2_ppm"] for _, r in rules] == [4200, 4300]
    assert [d["co2_ppm"] for d in sio.named("telemetry")] == [4200, 4300]
    assert [p.get("replay") for _, p in forwards] == [None, None]


async def test_pi_clock_behind_the_node_still_evaluates_rules(monkeypatch, rules):
    _pi_clock(monkeypatch, -300)
    await _handle_message(_Sio(), TOPIC, {"temp_f": 91.0, "ts": time.time()})
    assert [r["temp_f"] for _, r in rules] == [91.0]


async def test_first_synced_frame_ten_minutes_behind_the_pi_is_live(rules, forwards):
    old = time.time() - 600
    await _handle_message(_Sio(), TOPIC, {"humidity": 70.0, "ts": old})
    assert [r["humidity"] for _, r in rules] == [70.0]
    # Stored at the node's own time, forwarded as live.
    rows = await _rows("humidity")
    assert len(rows) == 1 and abs(rows[0]["timestamp"] - old) < 0.01
    assert [p.get("replay") for _, p in forwards] == [None]


async def test_unsynced_frames_do_not_make_later_synced_frames_look_late(monkeypatch, rules):
    """Uptime-ts frames are stamped with the Pi's (fast) clock; the node's
    first synced frames after that are still live."""
    _pi_clock(monkeypatch, +90)
    await _handle_message(_Sio(), TOPIC, {"temp_f": 70.0, "ts": 5000})
    await _handle_message(_Sio(), TOPIC, {"temp_f": 71.0, "ts": time.time()})
    assert [r["temp_f"] for _, r in rules] == [70.0, 71.0]


# ── what still is not live ────────────────────────────────────────────────


async def test_replay_frame_is_never_live(rules, forwards):
    now = time.time()
    await _handle_message(_Sio(), TOPIC, {"humidity": 88.0, "ts": now})
    await _handle_message(_Sio(), TOPIC, {"humidity": 70.0, "ts": now + 5, "replay": True})
    assert [r["humidity"] for _, r in rules] == [88.0]
    assert [p.get("replay") for _, p in forwards] == [None, True]


async def test_out_of_order_frame_is_stored_but_not_live(rules, forwards):
    sio = _Sio()
    now = time.time()
    before = get_reliability_counters()["non_live_frames"]["out_of_order"]
    await _handle_message(sio, TOPIC, {"humidity": 88.0, "ts": now})
    await _handle_message(sio, TOPIC, {"humidity": 70.0, "ts": now - 30})
    assert [r["humidity"] for _, r in rules] == [88.0]
    assert [d["humidity"] for d in sio.named("telemetry")] == [88.0]
    assert [(p["humidity"], p.get("replay")) for _, p in forwards] == [(88.0, None), (70.0, True)]
    assert len(await _rows("humidity")) == 2
    assert get_reliability_counters()["non_live_frames"]["out_of_order"] == before + 1


async def test_same_second_frames_are_both_live(rules):
    now = float(int(time.time()))
    await _handle_message(_Sio(), TOPIC, {"temp_f": 70.0, "ts": now})
    await _handle_message(_Sio(), TOPIC, {"temp_f": 71.0, "ts": now})
    assert [r["temp_f"] for _, r in rules] == [70.0, 71.0]


async def test_newer_frame_after_an_out_of_order_one_is_live(rules):
    now = time.time()
    await _handle_message(_Sio(), TOPIC, {"temp_f": 70.0, "ts": now})
    await _handle_message(_Sio(), TOPIC, {"temp_f": 60.0, "ts": now - 20})
    await _handle_message(_Sio(), TOPIC, {"temp_f": 72.0, "ts": now + 60})
    assert [r["temp_f"] for _, r in rules] == [70.0, 72.0]


async def test_ordering_is_tracked_per_node(rules):
    now = time.time()
    await _handle_message(_Sio(), "sporeprint/node-a/telemetry", {"temp_f": 70.0, "ts": now})
    await _handle_message(_Sio(), "sporeprint/node-b/telemetry", {"temp_f": 71.0, "ts": now - 30})
    assert [n for n, _ in rules] == ["node-a", "node-b"]


async def test_node_clock_stepping_back_does_not_stall_automation(rules, caplog):
    """A node that synced to a bogus future time and then corrected must not
    sit non-live until real time catches up with the bogus one."""
    now = time.time()
    await _handle_message(_Sio(), TOPIC, {"temp_f": 70.0, "ts": now + 86_400})
    with caplog.at_level(logging.WARNING, logger="app.mqtt"):
        await _handle_message(_Sio(), TOPIC, {"temp_f": 71.0, "ts": now})
    await _handle_message(_Sio(), TOPIC, {"temp_f": 72.0, "ts": now + 60})
    assert [r["temp_f"] for _, r in rules] == [70.0, 71.0, 72.0]
    assert any("stepped back" in r.getMessage() for r in caplog.records)


# ── skew is surfaced, not acted on ────────────────────────────────────────


async def test_large_skew_logs_one_rate_limited_warning(monkeypatch, rules, caplog):
    _pi_clock(monkeypatch, +300)
    with caplog.at_level(logging.WARNING, logger="app.mqtt"):
        for _ in range(3):
            await _handle_message(_Sio(), TOPIC, {"temp_f": 70.0, "ts": time.time()})
    skew_logs = [r for r in caplog.records if "clock" in r.getMessage() and NODE in r.getMessage()]
    assert len(skew_logs) == 1
    assert skew_logs[0].levelno == logging.WARNING


async def test_small_skew_is_not_logged(monkeypatch, rules, caplog):
    _pi_clock(monkeypatch, +30)
    with caplog.at_level(logging.WARNING, logger="app.mqtt"):
        await _handle_message(_Sio(), TOPIC, {"temp_f": 70.0, "ts": time.time()})
    assert not [r for r in caplog.records if "clock" in r.getMessage()]


async def test_skew_is_reported_per_node_in_reliability_counters(monkeypatch, rules):
    _pi_clock(monkeypatch, +300)
    await _handle_message(_Sio(), TOPIC, {"temp_f": 70.0, "ts": time.time()})
    await _handle_message(_Sio(), "sporeprint/relay-01/telemetry",
                          {"temp_f": 70.0, "ts": time.time() + 295})
    skew = get_reliability_counters()["node_clock_skew"]
    assert skew[NODE]["skew_seconds"] == pytest.approx(300, abs=2)
    assert skew[NODE]["skewed"] is True
    assert skew["relay-01"]["skew_seconds"] == pytest.approx(5, abs=2)
    assert skew["relay-01"]["skewed"] is False


async def test_unsynced_and_replayed_frames_do_not_report_skew(rules):
    await _handle_message(_Sio(), TOPIC, {"temp_f": 70.0, "ts": 5000})
    await _handle_message(_Sio(), TOPIC,
                          {"temp_f": 70.0, "ts": time.time() - 3600, "replay": True})
    assert NODE not in get_reliability_counters()["node_clock_skew"]


async def test_skew_table_is_bounded(rules, monkeypatch):
    monkeypatch.setattr(mqtt, "_NODE_CLOCK_TRACK_CAP", 3)
    now = time.time()
    for i in range(5):
        await _handle_message(_Sio(), f"sporeprint/n{i}/telemetry", {"temp_f": 70.0, "ts": now})
    assert sorted(get_reliability_counters()["node_clock_skew"]) == ["n2", "n3", "n4"]


def test_skew_is_in_the_health_detail_endpoint(client):
    mqtt._node_clock["climate-01"] = {"skew_seconds": 300.0, "observed_at": time.time(),
                                      "skewed": True}
    body = client.get("/api/health/detail/system").json()
    assert body["reliability"]["node_clock_skew"]["climate-01"]["skew_seconds"] == 300.0
    assert "non_live_frames" in body["reliability"]
