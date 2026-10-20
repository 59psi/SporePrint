"""The automation routes the dashboard's Automation page reads.

- PATCH /api/automation/rules/{id}/toggle flips the flag in one statement, so
  toggles that overlap (a double click, two tabs) each flip it once.
- GET /api/automation/firings/stats counts every firing in its window and
  each rule's newest firing of all time — not the newest page of
  GET /firings, which a busy week overflows.
"""

import asyncio
import time

import app.automation.engine as engine
from app.automation.models import AutomationRule
from app.automation.service import create_rule, firing_stats, rules_generation, toggle_rule
from app.db import get_db

DAY = 86400


def _rule(name: str = "Vent") -> AutomationRule:
    return AutomationRule.model_validate({
        "name": name, "priority": 5, "cooldown_seconds": 0,
        "condition": {"type": "threshold",
                      "threshold": {"sensor": "temp_f", "operator": "gt", "value": 0}},
        "action": {"target": "relay-01", "channel": "fae", "state": "on"},
    })


async def _enabled(rule_id: int) -> int:
    async with get_db() as db:
        cursor = await db.execute("SELECT enabled FROM automation_rules WHERE id = ?", (rule_id,))
        return (await cursor.fetchone())["enabled"]


async def _firings(rows: list[tuple[int | None, float, str]]) -> None:
    async with get_db() as db:
        await db.executemany(
            "INSERT INTO automation_firings (rule_id, rule_name, timestamp, status) VALUES (?, 'r', ?, ?)",
            rows,
        )
        await db.commit()


# ── toggle ────────────────────────────────────────────────────────────────


async def test_overlapping_toggles_each_flip_the_rule_once():
    rule_id = await create_rule(_rule())
    assert await _enabled(rule_id) == 1
    results = await asyncio.gather(*(toggle_rule(rule_id) for _ in range(4)))
    # four flips: each saw the one before it, so the answers alternate
    assert sorted(results) == [False, False, True, True]
    assert await _enabled(rule_id) == 1
    results = await asyncio.gather(*(toggle_rule(rule_id) for _ in range(3)))
    assert sorted(results) == [False, False, True]
    assert await _enabled(rule_id) == 0


def test_the_toggle_route_answers_the_new_state_and_invalidates_the_rule_cache(client):
    rule_id = client.get("/api/automation/rules").json()[0]["id"]
    before = client.get(f"/api/automation/rules/{rule_id}").json()["enabled"]
    generation = rules_generation()
    r = client.patch(f"/api/automation/rules/{rule_id}/toggle")
    assert r.status_code == 200
    assert r.json() == {"id": rule_id, "enabled": not before}
    assert rules_generation() > generation
    assert engine._cache_generation != rules_generation()  # the next load reads the table
    assert client.patch("/api/automation/rules/987654/toggle").status_code == 404


# ── firing stats ──────────────────────────────────────────────────────────


async def test_stats_count_the_window_and_keep_each_rules_newest_firing():
    empty = await firing_stats(7)
    assert (empty["fires"], empty["failed"], empty["rules"]) == (0, 0, [])
    now = time.time()
    await _firings([
        (1, now - 60, "sent"),
        (1, now - 2 * DAY, "failed"),
        (1, now - 6 * DAY, "sent"),
        (1, now - 9 * DAY, "failed"),  # outside the window
        (2, now - 10 * DAY, "sent"),    # fired, but not this week
        (None, now - 3600, "failed"),   # a safety cutoff (no rule id)
    ])
    stats = await firing_stats(7)
    assert abs(stats["since"] - (now - 7 * DAY)) < 5
    assert stats["fires"] == 4 and stats["failed"] == 2
    by_rule = {r["rule_id"]: r for r in stats["rules"]}
    assert set(by_rule) == {1, 2}
    assert by_rule[1]["fires"] == 3 and by_rule[1]["failed"] == 1
    assert abs(by_rule[1]["last_fired"] - (now - 60)) < 1
    assert by_rule[2]["fires"] == 0 and by_rule[2]["failed"] == 0
    assert abs(by_rule[2]["last_fired"] - (now - 10 * DAY)) < 1


async def test_stats_are_not_cut_to_the_newest_page_of_firings(client):
    # A busy week: 600 firings of one rule bury another rule's firing from
    # five days ago below the newest 500 rows the page used to read.
    now = time.time()
    await _firings([(3, now - 5 * DAY, "sent")] + [(4, now - i * 60, "sent") for i in range(600)])
    newest_page = client.get("/api/automation/firings?limit=500").json()
    assert all(f["rule_id"] == 4 for f in newest_page)

    r = client.get("/api/automation/firings/stats?days=7")
    assert r.status_code == 200
    body = r.json()
    by_rule = {row["rule_id"]: row for row in body["rules"]}
    assert by_rule[4]["fires"] == 600
    assert by_rule[3]["fires"] == 1
    assert abs(by_rule[3]["last_fired"] - (now - 5 * DAY)) < 1
    assert body["fires"] == 601


def test_stats_window_is_validated(client):
    assert client.get("/api/automation/firings/stats").status_code == 200  # 7 days by default
    assert client.get("/api/automation/firings/stats?days=0").status_code == 422
    assert client.get("/api/automation/firings/stats?days=400").status_code == 422
