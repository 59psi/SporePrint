"""One rule-id wire type across every remote surface (regression).

A rule's identity is an int — ``AutomationRule.id`` and the SQLite PK are both
int. Two cloud-originated surfaces reach automation rules by id:

  * the cloud ``system`` command, channel ``rule`` (temporary suspend) —
    ``_dispatch_system_command`` — which USED to require ``payload.rule_id`` be
    a ``str`` and reject an int outright;
  * the integrations-proxy automation CRUD (``automation_update`` /
    ``automation_delete``) which USED to require an ``int`` and reject a str.

So the exact same numeric id was accepted by one surface and rejected by the
other — a caller sending ``5`` (or ``"5"``) was stranded on one path. Both now
normalise through ``automation.service.normalize_rule_id``: a numeric id in
either wire form resolves to the same int on every surface; non-numeric / empty
/ None is rejected uniformly.
"""

import pytest

from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.automation.service import create_rule, get_rule, normalize_rule_id
from app.cloud import integrations_proxy
from app.cloud.service import _dispatch_system_command


class _FakeSio:
    def __init__(self) -> None:
        self.emits: list[tuple[str, dict]] = []

    async def emit(self, event: str, data: dict) -> None:
        self.emits.append((event, data))


def _rule(name: str = "contract-rule") -> AutomationRule:
    return AutomationRule(
        name=name,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="lt", value=80),
        ),
        action=RuleAction(target="relay-01", channel="fae", state="on"),
        log_to_session=False,
    )


def _rule_payload() -> dict:
    return {
        "name": "updated",
        "condition": {
            "type": "threshold",
            "threshold": {"sensor": "humidity", "operator": "lt", "value": 90},
        },
        "action": {"target": "relay-01", "channel": "fae", "state": "on"},
    }


# ── normalize_rule_id: the shared canonicaliser ────────────────────────────

def test_normalize_accepts_int_and_numeric_str_and_rejects_junk():
    assert normalize_rule_id(5) == 5
    assert normalize_rule_id("5") == 5
    assert normalize_rule_id("  7 ") == 7          # surrounding whitespace tolerated
    assert normalize_rule_id(0) == 0
    assert normalize_rule_id("seven") is None      # non-numeric string
    assert normalize_rule_id("") is None
    assert normalize_rule_id(None) is None
    # bool is an int subclass — must NOT sneak through as 0/1
    assert normalize_rule_id(True) is None
    assert normalize_rule_id(False) is None


# ── system 'rule' suspend path: an int id is now accepted (was rejected) ───

async def test_system_rule_suspend_accepts_int_rule_id():
    rid = await create_rule(_rule())
    assert isinstance(rid, int)

    # Pre-fix this returned (False, "rule_suspend requires payload.rule_id")
    # because the int failed the isinstance(str) guard.
    ok, err = await _dispatch_system_command("rule", {"rule_id": rid, "minutes": 15})
    assert ok, err
    assert err is None


async def test_system_rule_suspend_accepts_numeric_str_rule_id():
    rid = await create_rule(_rule())
    ok, err = await _dispatch_system_command("rule", {"rule_id": str(rid), "minutes": 15})
    assert ok, err


async def test_system_rule_suspend_rejects_missing_and_non_numeric():
    for bad in (None, "", "not-a-number"):
        ok, err = await _dispatch_system_command("rule", {"rule_id": bad})
        assert not ok
        assert err == "rule_suspend requires payload.rule_id"


# ── integrations-proxy CRUD: a numeric-string id is now accepted (was not) ─

async def test_proxy_automation_delete_accepts_numeric_str():
    sio = _FakeSio()
    rid = await create_rule(_rule())

    # Pre-fix a str failed isinstance(int) and raised "requires payload.rule_id".
    await integrations_proxy.handle_request(
        sio,
        {"id": "c1", "action": "automation_delete", "payload": {"rule_id": str(rid)}},
    )
    body = sio.emits[0][1]
    assert body["success"] is True, body
    assert body["body"]["id"] == rid
    assert await get_rule(rid) is None, "rule row must actually be deleted"


async def test_proxy_automation_delete_accepts_int():
    sio = _FakeSio()
    rid = await create_rule(_rule())
    await integrations_proxy.handle_request(
        sio,
        {"id": "c2", "action": "automation_delete", "payload": {"rule_id": rid}},
    )
    assert sio.emits[0][1]["success"] is True
    assert await get_rule(rid) is None


async def test_proxy_automation_update_accepts_numeric_str():
    sio = _FakeSio()
    rid = await create_rule(_rule())
    await integrations_proxy.handle_request(
        sio,
        {
            "id": "c3",
            "action": "automation_update",
            "payload": {"rule_id": str(rid), "rule": _rule_payload()},
        },
    )
    body = sio.emits[0][1]
    assert body["success"] is True, body
    assert body["body"]["id"] == rid
    updated = await get_rule(rid)
    assert updated is not None and updated["name"] == "updated"


async def test_proxy_automation_delete_still_rejects_non_numeric():
    sio = _FakeSio()
    await integrations_proxy.handle_request(
        sio,
        {"id": "c4", "action": "automation_delete", "payload": {"rule_id": "seven"}},
    )
    body = sio.emits[0][1]
    assert body["success"] is False
    assert body["status"] == 400


# ── the two surfaces now agree: one id works on both ───────────────────────

async def test_same_numeric_id_is_honoured_by_both_surfaces():
    """A single caller-supplied numeric id reaches the suspend path AND the
    CRUD path — the mismatch that stranded one of them is gone."""
    rid = await create_rule(_rule())

    ok, err = await _dispatch_system_command("rule", {"rule_id": rid, "minutes": 5})
    assert ok, f"system suspend rejected int id: {err}"

    sio = _FakeSio()
    await integrations_proxy.handle_request(
        sio,
        {"id": "both", "action": "automation_delete", "payload": {"rule_id": rid}},
    )
    assert sio.emits[0][1]["success"] is True, "CRUD path rejected the same int id"
