"""Shared fixtures and builders for the automation, safety-ceiling and smart-plug tests.

Not collected by pytest (leading underscore). A test module imports the
fixtures it uses by name; pytest registers a fixture found in a module's
namespace, and ``engine_state`` is autouse wherever it is imported.
"""

import asyncio
import importlib
import json
import time
from unittest.mock import patch

import httpx
import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
import app.sessions.service as sessions_service
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleCondition,
    ThresholdCondition,
)
from app.db import get_db
from app.integrations import _actions as vendor_actions
from app.integrations import _registry
from app.sessions.models import SessionCreate
from app.sessions.service import create_session

kasa_driver = importlib.import_module("app.integrations.kasa.driver")
agrowtek_driver = importlib.import_module("app.integrations.agrowtek.driver")

# The real sleep, captured before any fixture patches asyncio.sleep (the
# engine's sleep IS asyncio.sleep: patching it patches it for everyone).
REAL_SLEEP = asyncio.sleep
_REAL_LOCALTIME = time.localtime

RELAY_CHANNELS = ["fae", "exhaust", "circulation", "aux"]
LIGHT_CHANNELS = ["white", "blue", "red", "far_red"]


# ── engine state conftest does not reset ───────────────────────────────────


@pytest.fixture(autouse=True)
def engine_state():
    """Start and end every test with the engine unpaused and no per-actuator
    lock, ceiling deadline or last-ON time left over. A lock binds to the
    event loop it was first contended on, and each test runs its own loop."""
    def _clear():
        engine._paused = False
        engine._pause_loaded = False
        engine._actuator_locks.clear()
        engine._safety_deadlines.clear()
        engine._safety_last_on.clear()

    _clear()
    yield
    _clear()


# ── the engine's sleep ─────────────────────────────────────────────────────


@pytest.fixture
def fast_sleep(monkeypatch):
    """Every sleep returns after one loop yield; the requested delays, in order."""
    delays: list[float] = []

    async def _fast(delay):
        delays.append(delay)
        await REAL_SLEEP(0)

    monkeypatch.setattr(engine.asyncio, "sleep", _fast)
    return delays


@pytest.fixture
def frozen_sleep(monkeypatch):
    """Sleeps never return: a ceiling stays armed for the whole test."""
    async def _never(_delay):
        await asyncio.Event().wait()

    monkeypatch.setattr(engine.asyncio, "sleep", _never)


@pytest.fixture
def gated_sleep(monkeypatch):
    """Sleeps wait until the returned Event is set, then return at once."""
    gate = asyncio.Event()

    async def _gated(_delay):
        await gate.wait()

    monkeypatch.setattr(engine.asyncio, "sleep", _gated)
    return gate


async def drain(key: str, timeout: float = 2.0) -> None:
    """Wait for the ceiling armed under `key` to finish its trip."""
    task = engine._safety_tasks.get(key)
    assert task is not None, f"no safety ceiling armed for {key}"
    await asyncio.wait_for(asyncio.shield(task), timeout=timeout)


def ended(task: asyncio.Task) -> bool:
    return task.cancelled() or task.done()


# ── alerts ─────────────────────────────────────────────────────────────────


@pytest.fixture
def quiet_alerts(monkeypatch):
    """No ntfy page and no cloud forward."""
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(engine, "notify_critical", _noop)
    monkeypatch.setattr(engine, "notify_warning", _noop)
    monkeypatch.setattr(engine, "co2_alert", _noop)
    monkeypatch.setattr(cloud_service, "forward_event", _noop)


@pytest.fixture
def alerts(monkeypatch):
    """Every page the engine sends, by tier, and every event it forwards:
    critical / warning are (title, message); co2 the ppm; co2_pages
    (ppm, node, kwargs); forward (event type, data)."""
    rec: dict[str, list] = {"critical": [], "warning": [], "co2": [], "co2_pages": [],
                            "forward": []}

    async def _critical(title, message, tags=None, **kw):
        rec["critical"].append((title, message))

    async def _warning(title, message, dedup_key=None, **kw):
        rec["warning"].append((title, message))

    async def _co2(ppm, node_id=None, **kw):
        rec["co2"].append(ppm)
        rec["co2_pages"].append((ppm, node_id, kw))

    async def _forward(event_type, data):
        rec["forward"].append((event_type, data))

    monkeypatch.setattr(engine, "notify_critical", _critical)
    monkeypatch.setattr(engine, "notify_warning", _warning)
    monkeypatch.setattr(engine, "co2_alert", _co2)
    monkeypatch.setattr(cloud_service, "forward_event", _forward)
    return rec


class NtfyRecorder:
    """Stands in for httpx.AsyncClient inside notifications.notify(): every
    page body that would have been POSTed, in .posts."""

    posts: list[dict] = []

    def __init__(self, *args, **kwargs):  # the notifier passes its TLS context
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, timeout=None):
        NtfyRecorder.posts.append(json)
        return httpx.Response(200, request=httpx.Request("POST", url))


# ── vendor writes ──────────────────────────────────────────────────────────


@pytest.fixture
def dispatch_calls(monkeypatch):
    """Vendor dispatches the engine makes, as (slug, action, params)."""
    calls: list[tuple[str, str, dict]] = []

    async def _dispatch(slug, action, params):
        calls.append((slug, action, dict(params)))
        return {"ok": True}

    monkeypatch.setattr(vendor_actions, "dispatch", _dispatch)
    return calls


@pytest.fixture
def kasa_wire(monkeypatch):
    """What reaches a Kasa plug, as (ip, payload), through the real dispatcher."""
    sent: list[tuple[str, dict]] = []

    async def fake_query(ip, payload, timeout):
        sent.append((ip, payload))
        return {}

    monkeypatch.setattr(kasa_driver, "_kasa_query", fake_query)
    return sent


@pytest.fixture
def agrowtek_wire(monkeypatch):
    """What reaches an Agrowtek controller, as (url, body), through the real dispatcher."""
    drv = _registry.registered_drivers()["agrowtek"]
    monkeypatch.setattr(drv, "_cfg", agrowtek_driver.AgrowtekConfig(
        base_url="http://10.0.0.30", api_key="k"))
    sent: list[tuple[str, dict]] = []

    async def fake_put(self, url, headers=None, json=None, **kwargs):
        sent.append((str(url), json))
        return httpx.Response(200, json={})

    monkeypatch.setattr(httpx.AsyncClient, "put", fake_put)
    return sent



@pytest.fixture
def json_publishes(monkeypatch):
    """The JSON (native node) commands session-end safing publishes, as
    (topic, payload); each reported published."""
    calls: list[tuple[str, dict]] = []

    async def _fake_publish(topic, payload):
        calls.append((topic, payload))
        return True

    monkeypatch.setattr(sessions_service, "mqtt_publish", _fake_publish)
    return calls

# ── the wall clock ─────────────────────────────────────────────────────────


def local(hour: int, minute: int = 0, second: float = 0.0) -> float:
    """Epoch seconds for a fixed Monday (2026-07-13) at a LOCAL clock time."""
    return time.mktime((2026, 7, 13, hour, minute, 0, 0, 0, -1)) + second


def clock(ts: float):
    """Freeze time.time and time.localtime at `ts` (a context manager)."""
    return patch.multiple(
        time, time=lambda: ts,
        localtime=lambda t=None: _REAL_LOCALTIME(ts if t is None else t),
    )


# ── rules ──────────────────────────────────────────────────────────────────


def threshold(sensor: str, operator: str, value: float | None = None,
              profile_ref: str | None = None) -> RuleCondition:
    return RuleCondition(type=ConditionType.THRESHOLD, threshold=ThresholdCondition(
        sensor=sensor, operator=operator, value=value, profile_ref=profile_ref))


def make_rule(action, *, condition: RuleCondition | None = None, ceiling: int | None = None,
              name: str = "guard", rule_id: int | None = 1, **kw) -> AutomationRule:
    """A rule on `action` (by default "temp_f below 60"), with a
    safety_max_on_seconds of `ceiling`."""
    return AutomationRule(
        id=rule_id, name=name, condition=condition or threshold("temp_f", "lt", 60),
        action=action, safety_max_on_seconds=ceiling, **kw,
    )


# ── rows ───────────────────────────────────────────────────────────────────


async def rows(sql: str, *params) -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(sql, params)
        return [dict(r) for r in await cursor.fetchall()]


async def register_node(node_id: str, node_type: str = "relay",
                        channels: list[str] | None = None, *,
                        last_seen: float | None = None) -> None:
    """A node registered the way provisioning does (channels None: none reported yet)."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, roles, channels, last_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (node_id, node_type, json.dumps([node_type]),
             json.dumps(channels) if channels is not None else None,
             time.time() if last_seen is None else last_seen),
        )
        await db.commit()


async def insert_plug(plug_id: str, plug_type: str, prefix: str, *, role: str | None = None,
                      config: dict | str | None = None, status: str = "unknown",
                      last_state: str | None = None, last_seen: float | None = None) -> None:
    """A smart_plugs row written straight to the table (register_plug checks
    the prefix; this does not, so a test can store one it refuses)."""
    if isinstance(config, dict):
        config = json.dumps(config)
    async with get_db() as db:
        await db.execute(
            "INSERT INTO smart_plugs (plug_id, name, plug_type, mqtt_topic_prefix, device_role, "
            "config, status, last_state, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (plug_id, plug_id, plug_type, prefix, role, config, status, last_state, last_seen),
        )
        await db.commit()


async def plug_row(plug_id: str) -> dict | None:
    found = await rows("SELECT * FROM smart_plugs WHERE plug_id = ?", plug_id)
    return found[0] if found else None


async def chamber(name: str, node_ids: list[str]) -> int:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO chambers (name, node_ids) VALUES (?, ?)", (name, json.dumps(node_ids)),
        )
        await db.commit()
        return cursor.lastrowid


async def insert_watchdog(target: str, channel: str | None, rule_name: str,
                          expires_at: float, *, armed_at: float | None = None) -> None:
    """A persisted safety ceiling, as a running Pi leaves one behind: armed
    by default a minute before it expired, or a minute ago if it has not
    (a row armed in the future says the clock is behind: rehydrate fires it
    at once)."""
    if armed_at is None:
        armed_at = min(expires_at, time.time()) - 60
    async with get_db() as db:
        await db.execute(
            "INSERT INTO safety_watchdogs (target, channel, rule_name, armed_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (target, channel, rule_name, armed_at, expires_at),
        )
        await db.commit()


async def watchdog_rows() -> list[dict]:
    return await rows("SELECT target, channel, rule_name, expires_at FROM safety_watchdogs "
                      "ORDER BY expires_at, target")


async def firings(rule_name: str | None = None) -> list[dict]:
    """automation_firings rows (rule_name, status, error), oldest first."""
    if rule_name is None:
        return await rows("SELECT rule_name, status, error FROM automation_firings ORDER BY id")
    return await rows("SELECT rule_name, status, error FROM automation_firings "
                      "WHERE rule_name = ? ORDER BY id", rule_name)


async def start_grow(species: str = "blue_oyster", phase: str | None = None, **kw) -> dict:
    """An active session (phase None: the profile's first)."""
    if phase is not None:
        kw["current_phase"] = phase
    return await create_session(SessionCreate(
        name=kw.pop("name", f"{species}-{phase}"), species_profile_id=species,
        substrate=kw.pop("substrate", "test"), **kw,
    ))


# ── socket.io and the MQTT loop ────────────────────────────────────────────


class FakeSio:
    """Records every Socket.IO emit as (event, data)."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.events.append((event, data))


class MqttMessage:
    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


def fake_mqtt_client(messages: list[MqttMessage], published: list[tuple[str, str]]):
    """An aiomqtt.Client stand-in for mqtt.start_mqtt: it yields `messages`
    (raw bytes, as the broker delivers them), records what the server
    publishes, then cancels the loop (start_mqtt returns cleanly on that)."""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def subscribe(self, topic):
            return None

        async def publish(self, topic, payload):
            published.append((topic, payload))

        @property
        def messages(self):
            async def _gen():
                for m in messages:
                    yield m
                raise asyncio.CancelledError

            return _gen()

    return _Client
