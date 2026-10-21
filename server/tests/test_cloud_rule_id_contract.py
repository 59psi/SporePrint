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

from app.automation.engine import is_overridden
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
from app.config import settings
from tests._builders import register_node
from tests._fakes import RecordingSio


@pytest.fixture(autouse=True)
async def _proxy_env(monkeypatch, _db):
    """Unsigned frames with strict signing off (the signature gate has its
    own suite), and a paired relay node so relay-01 rules pass the editor's
    checks."""
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", False)
    await register_node("node-relay-1", "relay", channels=["aux", "circulation", "exhaust", "fae"])


def _rule() -> AutomationRule:
    return AutomationRule(
        name="contract-rule",
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


async def _proxy(action: str, payload: dict) -> dict:
    sio = RecordingSio()
    await integrations_proxy.handle_request(sio, {"id": "c1", "action": action, "payload": payload})
    return sio.last("integrations_response")


# ── normalize_rule_id: the shared canonicaliser ────────────────────────────

def test_normalize_accepts_int_and_numeric_str_and_rejects_junk():
    cases = {5: 5, "5": 5, "  7 ": 7, 0: 0, "seven": None, "": None, None: None}
    assert {raw: normalize_rule_id(raw) for raw in cases} == cases
    # bool is an int subclass — must NOT sneak through as 0/1
    assert normalize_rule_id(True) is None
    assert normalize_rule_id(False) is None


# ── the same numeric id reaches every surface, in either wire form ─────────

@pytest.mark.parametrize("wire", [int, str], ids=["int", "numeric-str"])
async def test_a_numeric_rule_id_reaches_the_suspend_and_crud_surfaces(wire):
    """Pre-fix an int failed the suspend path's isinstance(str) guard and a
    str failed the CRUD path's isinstance(int) guard."""
    rid = await create_rule(_rule())

    ok, err = await _dispatch_system_command("rule", {"rule_id": wire(rid), "minutes": 15})
    assert (ok, err) == (True, None)
    assert is_overridden("relay-01", "fae") is True  # the rule's own action target

    updated = await _proxy("automation_update", {"rule_id": wire(rid), "rule": _rule_payload()})
    assert updated["success"] is True, updated
    assert updated["body"]["id"] == rid
    assert (await get_rule(rid))["name"] == "updated"

    deleted = await _proxy("automation_delete", {"rule_id": wire(rid)})
    assert deleted["success"] is True, deleted
    assert deleted["body"]["id"] == rid
    assert await get_rule(rid) is None, "rule row must actually be deleted"


@pytest.mark.parametrize("bad", [None, "", "not-a-number"])
async def test_a_non_numeric_rule_id_is_refused_by_every_surface(bad):
    ok, err = await _dispatch_system_command("rule", {"rule_id": bad})
    assert (ok, err) == (False, "rule_suspend requires payload.rule_id")
    for action in ("automation_update", "automation_delete"):
        resp = await _proxy(action, {"rule_id": bad, "rule": _rule_payload()})
        assert (resp["success"], resp["status"]) == (False, 400), resp
        assert "payload.rule_id" in resp["error"]
