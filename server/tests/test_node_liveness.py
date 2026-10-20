"""The node-liveness sweeper (main._sweep_stale_nodes / _node_liveness_sweeper).

* The CRITICAL "node offline" page and the cloud's node_offline event never
  fired for a node the broker reported dead through its LWT — nearly every
  real outage (power or WiFi loss, a crash loop): the LWT set
  status='offline', and the sweeper only looked at rows whose status was not
  'offline'. Paging is now tracked apart from status (offline_notified_at):
  once per silence, re-armed by the node's next heartbeat or live 'online'.
* The sweeper held its write transaction open across the ntfy POST (5 s
  timeouts), so concurrent telemetry and rule-firing writes failed with
  'database is locked'. It now commits before paging.
* Local Socket.IO clients now hear node_status for a sweeper-detected offline
  and for the heartbeat that brings a node back.
"""

import asyncio
import time

import pytest

from app import main
from app.db import get_db
from app.health.service import _task_registry, register_task
from app.mqtt import _handle_message


class _Sio:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.events.append((event, data))

    def named(self, event):
        return [d for e, d in self.events if e == event]


@pytest.fixture()
def paged(monkeypatch):
    """Record the sweeper's pages, cloud events and local emits."""
    record = {"ntfy": [], "cloud": [], "sio": _Sio()}

    async def _node_offline(node_id):
        record["ntfy"].append(node_id)

    async def _forward_event(event, payload):
        record["cloud"].append((event, payload))

    monkeypatch.setattr(main, "node_offline", _node_offline)
    monkeypatch.setattr(main, "forward_event", _forward_event)
    monkeypatch.setattr(main, "sio", record["sio"])
    return record


async def _set_last_seen(node_id: str, ago: float) -> None:
    async with get_db() as db:
        await db.execute("UPDATE hardware_nodes SET last_seen = ? WHERE node_id = ?",
                         (time.time() - ago, node_id))
        await db.commit()


async def _row(node_id: str) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT status, offline_notified_at FROM hardware_nodes WHERE node_id = ?",
            (node_id,))
        return dict(await cursor.fetchone())


async def _heartbeat(sio, node_id: str) -> None:
    await _handle_message(sio, f"sporeprint/{node_id}/status/heartbeat",
                          {"type": "relay", "firmware_version": "5.2.2"})


async def _online_then_lwt(node_id: str) -> None:
    sio = _Sio()
    await _handle_message(sio, f"sporeprint/{node_id}/status", {"status": "online"})
    await _heartbeat(sio, node_id)
    # ~22 s after the node dies the broker publishes its will.
    await _handle_message(sio, f"sporeprint/{node_id}/status", {"status": "offline"})


async def test_a_node_the_broker_reported_dead_is_paged_once(paged):
    await _online_then_lwt("relay-a")
    assert (await _row("relay-a"))["status"] == "offline"
    await _set_last_seen("relay-a", 30 * 60)

    stale = await main._sweep_stale_nodes()

    assert [r["node_id"] for r in stale] == ["relay-a"]
    assert paged["ntfy"] == ["relay-a"]
    assert [(e, p["node_id"]) for e, p in paged["cloud"]] == [("node_offline", "relay-a")]
    assert paged["sio"].named("node_status") == [{"node_id": "relay-a", "status": "offline"}]
    assert (await _row("relay-a"))["offline_notified_at"] is not None

    # Every later sweep of the same silence sends nothing.
    assert await main._sweep_stale_nodes() == []
    assert await main._sweep_stale_nodes(now=time.time() + 86400) == []
    assert paged["ntfy"] == ["relay-a"] and len(paged["cloud"]) == 1


async def test_a_node_that_just_went_quiet_is_not_paged_yet(paged):
    await _online_then_lwt("relay-a")
    await _set_last_seen("relay-a", main._NODE_OFFLINE_THRESHOLD_SECONDS - 60)
    assert await main._sweep_stale_nodes() == []
    assert paged["ntfy"] == []


async def test_a_node_silent_without_a_will_is_still_paged(paged):
    await _heartbeat(_Sio(), "climate-b")
    await _set_last_seen("climate-b", 20 * 60)
    await main._sweep_stale_nodes()
    assert paged["ntfy"] == ["climate-b"]
    assert (await _row("climate-b"))["status"] == "offline"


async def test_a_heartbeat_re_arms_the_page(paged):
    await _online_then_lwt("relay-a")
    await _set_last_seen("relay-a", 30 * 60)
    await main._sweep_stale_nodes()

    sio = _Sio()
    await _heartbeat(sio, "relay-a")  # back
    assert await _row("relay-a") == {"status": "online", "offline_notified_at": None}
    assert sio.named("node_status") == [{"node_id": "relay-a", "status": "online"}]

    await _handle_message(sio, "sporeprint/relay-a/status", {"status": "offline"})
    await _set_last_seen("relay-a", 30 * 60)
    await main._sweep_stale_nodes()
    assert paged["ntfy"] == ["relay-a", "relay-a"]  # the second outage pages too


async def test_a_live_online_status_re_arms_but_a_replayed_one_does_not(paged):
    await _online_then_lwt("relay-a")
    await _set_last_seen("relay-a", 30 * 60)
    await main._sweep_stale_nodes()

    # The broker replays the stored 'online' on every Pi (re)subscribe; a dead
    # node must not be paged again after each restart.
    await _handle_message(_Sio(), "sporeprint/relay-a/status", {"status": "online"},
                          retained=True)
    assert (await _row("relay-a"))["offline_notified_at"] is not None

    await _handle_message(_Sio(), "sporeprint/relay-a/status", {"status": "online"})
    assert (await _row("relay-a"))["offline_notified_at"] is None


async def test_a_steady_heartbeat_emits_no_status_change(paged):
    sio = _Sio()
    await _heartbeat(sio, "relay-a")   # first heard: news
    await _heartbeat(sio, "relay-a")   # steady: not news
    assert sio.named("node_status") == [{"node_id": "relay-a", "status": "online"}]


async def test_pages_go_out_after_the_rows_are_committed(monkeypatch, paged):
    """The page used to run inside the open write transaction."""
    for node_id in ("relay-a", "relay-b"):
        await _online_then_lwt(node_id)
        await _set_last_seen(node_id, 30 * 60)
    seen = []

    async def _slow_page(node_id):
        # Another writer gets the lock at once while a page is in flight...
        async with get_db() as db:
            await db.execute("PRAGMA busy_timeout=0")
            await db.execute(
                "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) "
                "VALUES (?, 'climate-01', 'temp_f', 70.0)", (time.time(),))
            await db.commit()
            # ...and every swept row is already committed as paged.
            cursor = await db.execute(
                "SELECT COUNT(*) FROM hardware_nodes WHERE offline_notified_at IS NOT NULL")
            seen.append((await cursor.fetchone())[0])

    monkeypatch.setattr(main, "node_offline", _slow_page)
    await main._sweep_stale_nodes()
    assert seen == [2, 2]


async def test_a_failing_page_does_not_stop_the_others(monkeypatch, paged):
    for node_id in ("relay-a", "relay-b"):
        await _online_then_lwt(node_id)
        await _set_last_seen(node_id, 30 * 60)

    async def _boom(node_id):
        raise RuntimeError("ntfy down")

    monkeypatch.setattr(main, "node_offline", _boom)
    stale = await main._sweep_stale_nodes()
    assert {r["node_id"] for r in stale} == {"relay-a", "relay-b"}
    assert len(paged["cloud"]) == 2


# ── the loop reports its state to the task registry ───────────────────────

@pytest.fixture()
def sweeper_task(monkeypatch):
    monkeypatch.setattr(main, "_NODE_SWEEPER_INTERVAL_SECONDS", 0)
    _task_registry.clear()
    register_task("node_liveness_sweeper", "idle")
    yield
    _task_registry.clear()


async def _run_once(monkeypatch, sweep) -> None:
    done = asyncio.Event()

    async def _sweep(now=None):
        try:
            return await sweep()
        finally:
            done.set()

    monkeypatch.setattr(main, "_sweep_stale_nodes", _sweep)
    task = asyncio.create_task(main._node_liveness_sweeper())
    try:
        await asyncio.wait_for(done.wait(), timeout=2)
        await asyncio.sleep(0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_a_failing_sweep_shows_as_an_error(monkeypatch, sweeper_task):
    async def _fail():
        raise RuntimeError("database is locked")

    await _run_once(monkeypatch, _fail)
    entry = _task_registry["node_liveness_sweeper"]
    assert entry["status"] == "error"
    assert "database is locked" in entry["error"]


async def test_a_good_sweep_shows_as_idle(monkeypatch, sweeper_task):
    async def _ok():
        return []

    await _run_once(monkeypatch, _ok)
    entry = _task_registry["node_liveness_sweeper"]
    assert entry["status"] == "idle" and entry["last_run"] is not None
