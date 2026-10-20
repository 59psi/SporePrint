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

import httpx
import pytest
from fastapi import FastAPI, HTTPException

import app.automation.engine as engine
from app.automation.engine import _fire_rule
from app.automation.models import RuleAction
from app.cloud import integrations_proxy
from app.db import get_db
from app.integrations import _actions
from tests._pi_a_engine import (  # noqa: F401 (fixtures)
    agrowtek_wire,
    engine_state,
    frozen_sleep,
    kasa_driver,
    kasa_wire,
    make_rule,
)

HEATER = "vendor:kasa:10.0.0.20"
HEATER_KEY = f"{HEATER}:*"


def _rule(action: RuleAction, rule_id: int = 7, name: str = "Heater (kasa)"):
    return make_rule(action, ceiling=3600, name=name, rule_id=rule_id, log_to_session=False)


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
        raise kasa_driver.KasaError("connect refused")

    monkeypatch.setattr(kasa_driver, "_kasa_query", unreachable)
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch_manual("kasa", "set_power", {"ip": "10.0.0.20", "on": False})
    assert exc.value.status_code == 502
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


async def test_a_failing_listener_never_fails_a_write_that_went_out(kasa_wire, monkeypatch):
    async def _broken(*args, **kwargs):
        raise RuntimeError("listener bug")

    monkeypatch.setattr(_actions, "_write_listeners", [_broken])
    await _actions.dispatch_manual("kasa", "set_power", {"ip": "10.0.0.20", "on": False})
    assert kasa_wire == [("10.0.0.20", {"system": {"set_relay_state": {"state": 0}}})]


@pytest.mark.parametrize("action,params,expected", [
    ("set_power", {"ip": "10.0.0.20", "on": "off"}, False),
    ("set_power", {"ip": "10.0.0.20", "on": "1"}, True),
    ("set_power", {"ip": "10.0.0.20", "on": "on"}, True),
    ("set_power", {"ip": "10.0.0.20", "on": "maybe"}, None),
    ("set_power", {"on": True}, None),            # no device: nothing the ceiling can bound
    ("set_dim", {"ip": "10.0.0.20", "percent": "0"}, False),
    ("set_dim", {"ip": "10.0.0.20", "percent": "40"}, True),
    ("set_dim", {"ip": "10.0.0.20", "percent": "half"}, None),
])
def test_a_vendor_write_is_read_on_or_off_like_the_dispatcher_reads_it(action, params, expected):
    assert engine._vendor_params_on("kasa", action, params) is expected
