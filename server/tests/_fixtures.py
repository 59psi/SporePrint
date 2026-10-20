"""Opt-in fixtures shared by the server tests.

Registered from conftest.py (``pytest_plugins``): a test asks for one by
name and imports nothing. The helpers they are built on live in
tests/_fakes.py and tests/_timing.py.
"""

import asyncio
import importlib
import json
import os
import time
from types import SimpleNamespace

import httpx
import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
import app.mqtt
import app.sessions.service as sessions_service
from app.config import settings
from app.integrations import _actions as vendor_actions
from app.integrations import _registry
from tests._fakes import route_httpx, spy_ingest
from tests._timing import REAL_SLEEP

# The package rebinds `driver` to the driver instance; the module is what the
# wire fixtures patch.
kasa_driver = importlib.import_module("app.integrations.kasa.driver")
agrowtek_driver = importlib.import_module("app.integrations.agrowtek.driver")


async def _drop(*args, **kwargs):
    return None


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


# ── alerts ─────────────────────────────────────────────────────────────────


@pytest.fixture
def quiet_alerts(monkeypatch):
    """No ntfy page and no cloud forward from the engine."""
    monkeypatch.setattr(engine, "notify_critical", _drop)
    monkeypatch.setattr(engine, "notify_warning", _drop)
    monkeypatch.setattr(engine, "co2_alert", _drop)
    monkeypatch.setattr(cloud_service, "forward_event", _drop)


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


@pytest.fixture
def ntfy_posts(monkeypatch):
    """The JSON bodies the real notifier POSTs to ntfy, through a real httpx
    client on a MockTransport (so an encoding error surfaces as it would
    against a live server); cloud event forwards are dropped."""
    posts: list[dict] = []

    def _ntfy(request: httpx.Request) -> httpx.Response:
        if request.url.host != "ntfy.test":
            return httpx.Response(404)
        posts.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "x"})

    monkeypatch.setattr(settings, "ntfy_url", "http://ntfy.test")
    route_httpx(monkeypatch, _ntfy)
    monkeypatch.setattr(app.mqtt, "forward_event", _drop)
    monkeypatch.setattr(cloud_service, "forward_event", _drop)
    return posts


# ── what reaches a device ──────────────────────────────────────────────────


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


# ── the MQTT ingest path ───────────────────────────────────────────────────


@pytest.fixture
def ingest(monkeypatch) -> SimpleNamespace:
    """The ingest path with the rules engine and the cloud relay stubbed:
    .rules [(node_id, readings)] the engine was handed, .forwards
    [(node_id, payload)] forwarded to the cloud relay (see spy_ingest)."""
    return spy_ingest(monkeypatch)


# ── the Pi's time zone ─────────────────────────────────────────────────────


@pytest.fixture
def pacific_time():
    """The Pi's zone (setup.sh hands the host's TZ to the container)."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "America/Los_Angeles"
    time.tzset()
    yield
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()
