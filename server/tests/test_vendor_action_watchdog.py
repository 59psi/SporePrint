"""A manual vendor write is bookkept like a manual plug or node command.

A vendor rule (kasa.set_power on, safety_max_on_seconds) arms a safety
ceiling for that device. Switching the device OFF by hand — the Pi's
integrations actions route or the cloud's vendor_action RPC — must clear
that ceiling, as a manual plug OFF does. Otherwise the next automation ON
keeps the old deadline and trips early: a false "Safety cutoff" page and a
15-minute lockout of the heater. Rules and the watchdog's own OFF still go
through dispatch() and keep their own books.

A vendor param sent as text ("true", "50") is read the way the device gets
it, so a string ON arms the ceiling and gets an OFF of the matching type.
"""

from __future__ import annotations

import asyncio
import importlib

import httpx
import pytest
from fastapi import FastAPI

import app.automation.engine as engine
from app.automation.engine import _fire_rule
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.cloud import integrations_proxy
from app.db import get_db
from app.integrations import _actions, _registry

kasa_mod = importlib.import_module("app.integrations.kasa.driver")
agrowtek_mod = importlib.import_module("app.integrations.agrowtek.driver")

HEATER = "vendor:kasa:10.0.0.20"
HEATER_KEY = f"{HEATER}:*"


@pytest.fixture(autouse=True)
def _fresh_actuator_state():
    """Per-actuator locks bind to the loop they were first contended on, and
    each test gets its own loop — start every test with none."""
    engine._actuator_locks.clear()
    engine._safety_deadlines.clear()
    yield
    engine._actuator_locks.clear()


@pytest.fixture
def frozen_sleep(monkeypatch):
    """Engine sleeps never return — a ceiling stays armed for the whole test."""
    async def _never(_delay):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.automation.engine.asyncio.sleep", _never)


@pytest.fixture
def kasa_wire(monkeypatch):
    sent: list[tuple[str, dict]] = []

    async def fake_query(ip, payload, timeout):
        sent.append((ip, payload))
        return {}

    monkeypatch.setattr(kasa_mod, "_kasa_query", fake_query)
    return sent


@pytest.fixture
def agrowtek_wire(monkeypatch):
    drv = _registry.registered_drivers()["agrowtek"]
    monkeypatch.setattr(drv, "_cfg", agrowtek_mod.AgrowtekConfig(base_url="http://10.0.0.30", api_key="k"))
    sent: list[tuple[str, dict]] = []

    async def fake_put(self, url, headers=None, json=None, **kwargs):
        sent.append((str(url), json))
        return httpx.Response(200, json={})

    monkeypatch.setattr(httpx.AsyncClient, "put", fake_put)
    return sent


def _rule(action: RuleAction, rule_id: int = 7, name: str = "Heater (kasa)") -> AutomationRule:
    return AutomationRule(
        id=rule_id,
        name=name,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="temp_f", operator="lt", value=60),
        ),
        action=action,
        safety_max_on_seconds=3600,
        log_to_session=False,
    )


def _heater(on: object = True) -> RuleAction:
    return RuleAction(
        target=HEATER, vendor_slug="kasa", vendor_action="set_power",
        vendor_params={"ip": "10.0.0.20", "on": on},
    )


async def _watchdog_rows() -> list[str]:
    async with get_db() as db:
        cursor = await db.execute("SELECT target FROM safety_watchdogs ORDER BY target")
        return [row["target"] for row in await cursor.fetchall()]


async def test_manual_off_through_the_actions_route_clears_the_ceiling(
    frozen_sleep, kasa_wire, mock_mqtt,
):
    await _fire_rule(_rule(_heater()), {}, session=None)
    assert HEATER_KEY in engine._safety_tasks
    assert await _watchdog_rows() == [HEATER]

    app = FastAPI()
    app.include_router(_actions.router, prefix="/api/integrations")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://pi") as client:
        resp = await client.post("/api/integrations/kasa/actions/set_power",
                                 json={"ip": "10.0.0.20", "on": "off"})
    assert resp.status_code == 200, resp.text
    assert kasa_wire[-1] == ("10.0.0.20", {"system": {"set_relay_state": {"state": 0}}})
    assert HEATER_KEY not in engine._safety_tasks
    assert await _watchdog_rows() == []


async def test_manual_off_through_the_cloud_rpc_clears_the_ceiling(
    frozen_sleep, kasa_wire, mock_mqtt,
):
    await _fire_rule(_rule(_heater()), {}, session=None)
    await integrations_proxy._dispatch(
        "vendor_action", "kasa", {"action": "set_power", "ip": "10.0.0.20", "on": False},
    )
    assert HEATER_KEY not in engine._safety_tasks
    assert await _watchdog_rows() == []


async def test_a_refire_after_a_manual_off_starts_a_fresh_ceiling(
    frozen_sleep, kasa_wire, mock_mqtt,
):
    await _fire_rule(_rule(_heater()), {}, session=None)
    first_deadline = engine._safety_deadlines[HEATER_KEY]
    await _actions.dispatch_manual("kasa", "set_power", {"ip": "10.0.0.20", "on": False})
    # (No asyncio.sleep here: frozen_sleep freezes it for everyone.)
    await _fire_rule(_rule(_heater()), {}, session=None)
    # A held-ON re-fire keeps a running ceiling's deadline; the manual OFF
    # ended that one, so this ON is timed from now.
    assert engine._safety_deadlines[HEATER_KEY] > first_deadline


async def test_a_manual_on_leaves_the_ceiling_alone(frozen_sleep, kasa_wire, mock_mqtt):
    await _fire_rule(_rule(_heater()), {}, session=None)
    deadline = engine._safety_deadlines[HEATER_KEY]
    await _actions.dispatch_manual("kasa", "set_power", {"ip": "10.0.0.20", "on": "true"})
    assert engine._safety_deadlines[HEATER_KEY] == deadline


async def test_a_failed_manual_write_changes_nothing(frozen_sleep, kasa_wire, mock_mqtt, monkeypatch):
    await _fire_rule(_rule(_heater()), {}, session=None)

    async def unreachable(ip, payload, timeout):
        raise kasa_mod.KasaError("connect refused")

    monkeypatch.setattr(kasa_mod, "_kasa_query", unreachable)
    with pytest.raises(Exception):
        await _actions.dispatch_manual("kasa", "set_power", {"ip": "10.0.0.20", "on": False})
    assert HEATER_KEY in engine._safety_tasks, "the plug may still be ON"


async def test_rules_keep_their_own_books(frozen_sleep, kasa_wire, mock_mqtt, monkeypatch):
    heard: list[tuple] = []

    async def _spy(*args, **kwargs):
        heard.append(args)

    monkeypatch.setattr(_actions, "_write_listeners", [_spy])
    await _fire_rule(_rule(_heater()), {}, session=None)
    await _fire_rule(_rule(_heater(on=False), rule_id=8, name="Heater off"), {}, session=None)
    assert kasa_wire[-1][1] == {"system": {"set_relay_state": {"state": 0}}}
    assert HEATER_KEY not in engine._safety_tasks, "a rule's OFF still clears its ceiling"
    assert heard == [], "a rule firing is not a manual write"


async def test_a_string_on_arms_the_ceiling_and_its_off_matches(frozen_sleep, agrowtek_wire, mock_mqtt):
    pump = RuleAction(
        target="vendor:agrowtek:3", vendor_slug="agrowtek", vendor_action="set_output",
        vendor_params={"output_id": "3", "value": "true"},
    )
    await _fire_rule(_rule(pump), {}, session=None)
    # The device got a real true, and the ceiling is armed: read raw, the
    # string "true" was neither on nor off, so no ceiling was enforced.
    assert agrowtek_wire[-1] == ("http://10.0.0.30/api/outputs/3", {"value": True})
    assert "vendor:agrowtek:3:*" in engine._safety_tasks
    assert engine._vendor_safety_off("agrowtek", {"output_id": "3", "value": "true"}) == (
        "set_output", {"output_id": "3", "value": False})
    assert engine._vendor_safety_off("agrowtek", {"output_id": "3", "value": "50"}) == (
        "set_output", {"output_id": "3", "value": 0})


@pytest.mark.parametrize("params,expected", [
    ({"ip": "10.0.0.20", "on": "off"}, False),
    ({"ip": "10.0.0.20", "on": "1"}, True),
    ({"ip": "10.0.0.20", "on": "maybe"}, None),
])
def test_vendor_on_off_is_read_like_the_dispatcher(params, expected):
    assert engine._vendor_params_on("kasa", "set_power", params) is expected


@pytest.mark.parametrize("percent,expected", [("0", False), ("40", True), ("half", None)])
def test_dim_percent_text_is_read_like_the_dispatcher(percent, expected):
    params = {"ip": "10.0.0.20", "percent": percent}
    assert engine._vendor_params_on("kasa", "set_dim", params) is expected
