"""Built-in rules on a Pi that upgrades: what each release seeded becomes the
current built-in set, and nothing the operator removed comes back.

fixtures/released_builtin_rules.json holds the automation_rules rows each
release wrote into a fresh table, byte for byte (rule_data is json.dumps of
the object stored there): 0.2.0 to 4.1.5 seeded one set, 5.0.0 another, and
5.1.0 to 5.2.2 a third. Replaying them through seed_builtin_rules is the test
docs/automation-rules.md asks for: a built-in changed without its old form
recorded (SUPERSEDED_BUILTIN_RULES), or removed without RETIRED_BUILTIN_RULES,
fails here instead of silently staying old on every existing Pi. Add the seed
of a release whose built-ins change.
"""

import json
from pathlib import Path

import pytest

from app.automation.engine import _is_life_safety_rule, evaluate_rules
from app.automation.models import AutomationRule
from app.automation.service import (
    _same_rule,
    create_rule,
    deserialize_rule_row,
    seed_builtin_rules,
)
from app.automation.templates import (
    BUILTIN_RULES,
    LEGACY_BUILTIN_RULES,
    RETIRED_BUILTIN_RULES,
    SEEDED_BEFORE_V5,
    SEEDED_V5_0_TO_V5_1,
)
from app.db import get_db
from app.species.service import seed_builtins
from tests._pi_a_engine import clock, engine_state, local, quiet_alerts, start_grow  # noqa: F401

_RELEASED: dict[str, list[dict]] = json.loads(
    (Path(__file__).parent / "fixtures" / "released_builtin_rules.json").read_text(encoding="utf-8"))
_V4, _V5_0, _V5_1 = "0.2.0-4.1.5", "5.0.0-5.0.x", "5.1.0-5.2.2"

CURRENT = {r.name: r for r in BUILTIN_RULES}
# The names 5.0.0 added: what a Pi first seeded by 0.2-4.x has not been given.
ADDED_IN_V5 = set(SEEDED_V5_0_TO_V5_1) - set(SEEDED_BEFORE_V5)


async def _seed_as_release(label: str) -> None:
    """The table exactly as release `label` left it on first boot: one batch."""
    async with get_db() as db:
        for row in _RELEASED[label]:
            await db.execute(
                "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) "
                "VALUES (?, ?, ?, ?, ?)",
                (row["name"], row["description"], row["enabled"], row["priority"],
                 json.dumps(row["rule_data"])),
            )
        await db.commit()


async def _stored() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, enabled, priority, rule_data FROM automation_rules ORDER BY id")
        return [dict(r) for r in await cursor.fetchall()]


def _rule(row) -> AutomationRule:
    return AutomationRule.model_validate(deserialize_rule_row(row))


async def _names() -> set[str]:
    return {r["name"] for r in await _stored()}


async def _delete(*names: str) -> None:
    async with get_db() as db:
        for name in names:
            await db.execute("DELETE FROM automation_rules WHERE name = ?", (name,))
        await db.commit()


def _warnings(caplog, text: str) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelname == "WARNING" and text in r.getMessage()]


def test_the_fixture_is_what_the_seed_sets_say():
    assert [r["name"] for r in _RELEASED[_V4]] == list(SEEDED_BEFORE_V5)
    assert [r["name"] for r in _RELEASED[_V5_0]] == list(SEEDED_V5_0_TO_V5_1)
    assert [r["name"] for r in _RELEASED[_V5_1]] == list(SEEDED_V5_0_TO_V5_1)
    # Every name a release ever seeded is either shipped now or retired: a
    # built-in dropped from BUILTIN_RULES without RETIRED_BUILTIN_RULES would
    # keep running on every Pi that has it.
    seeded = {r["name"] for rows in _RELEASED.values() for r in rows}
    assert seeded <= set(CURRENT) | set(RETIRED_BUILTIN_RULES), seeded - set(CURRENT)
    assert not set(CURRENT) & set(RETIRED_BUILTIN_RULES)


@pytest.mark.parametrize("release", [_V4, _V5_0, _V5_1])
async def test_every_release_seed_becomes_the_current_built_ins(release, caplog):
    await _seed_as_release(release)
    with caplog.at_level("WARNING", logger="app.automation.service"):
        await seed_builtin_rules()

    rows = await _stored()
    by_name: dict[str, list[dict]] = {}
    for row in rows:
        by_name.setdefault(row["name"], []).append(row)
    retired = set(RETIRED_BUILTIN_RULES) if release == _V4 else set()
    assert set(by_name) == set(CURRENT) | retired
    for name, current in CURRENT.items():
        assert len(by_name[name]) == 1, name
        assert _same_rule(_rule(by_name[name][0]), current), f"{release}: {name} stayed old"
    for name in retired:
        assert by_name[name][0]["enabled"] == 0, name
    # Nobody edited these copies, so none is reported as edited.
    assert _warnings(caplog, "was edited") == []
    # Exactly the built-ins that release did not ship are added, and said so.
    new = set(CURRENT) - {r["name"] for r in _RELEASED[release]}
    if release == _V4:
        assert ADDED_IN_V5 <= new
    else:
        assert not (new & ADDED_IN_V5)
    added = _warnings(caplog, "Added built-in")
    if new:
        assert len(added) == 1 and all(name in added[0] for name in new)
    else:
        assert added == []
    # The 0.2-4.x Emergency CO2 Exhaust (fixed 3000 ppm, no phase scope,
    # priority 20) read as a life-safety rule and vented colonizing grows.
    emergency = _rule(by_name["Emergency CO2 Exhaust"][0])
    assert not _is_life_safety_rule(emergency)


async def test_a_second_boot_changes_nothing(caplog):
    await _seed_as_release(_V4)
    await seed_builtin_rules()
    before = await _stored()
    caplog.clear()
    with caplog.at_level("WARNING", logger="app.automation.service"):
        await seed_builtin_rules()
    assert await _stored() == before
    assert _warnings(caplog, "") == []



async def test_an_edited_copy_of_a_changed_built_in_is_left_alone_and_named(caplog):
    """An edited copy keeps its old logic, which priority arbitration can make
    matter (a forecast-only Pre-cool now holds the cooler on against the
    Cooling Cutoff), so it is not upgraded and the operator is told, at every
    boot. The unedited copies beside it are upgraded."""
    await _seed_as_release(_V5_0)
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT rule_data FROM automation_rules WHERE name = 'Pre-cool for Hot Forecast'"
        )).fetchone()
        data = json.loads(row["rule_data"])
        data["cooldown_seconds"] = 900
        await db.execute("UPDATE automation_rules SET rule_data = ? "
                         "WHERE name = 'Pre-cool for Hot Forecast'", (json.dumps(data),))
        await db.commit()
    for _ in range(2):  # two boots
        caplog.clear()
        with caplog.at_level("WARNING", logger="app.automation.service"):
            await seed_builtin_rules()
        edited = _warnings(caplog, "was edited")
        assert len(edited) == 1 and "Pre-cool for Hot Forecast" in edited[0]

    stored = {r["name"]: _rule(r) for r in await _stored()}
    kept = LEGACY_BUILTIN_RULES["Pre-cool for Hot Forecast"].model_copy(
        update={"cooldown_seconds": 900})
    assert _same_rule(stored["Pre-cool for Hot Forecast"], kept)
    assert stored["Pre-cool for Hot Forecast"].cooldown_seconds == 900
    for name in set(LEGACY_BUILTIN_RULES) - {"Pre-cool for Hot Forecast"}:
        assert _same_rule(stored[name], CURRENT[name]), name

# ── A Pi seeded before 5.2.0 recorded nothing about what it was given ──────


async def test_a_5_1_pi_keeps_deleted_and_renamed_built_ins_out(caplog):
    await _seed_as_release(_V5_1)
    await _delete("Mist (no humidifier)", "Photoperiod — Lights On")
    async with get_db() as db:
        await db.execute("UPDATE automation_rules SET name = 'Heater (mine)' "
                         "WHERE name = 'Heating Trigger'")
        await db.commit()
    with caplog.at_level("WARNING", logger="app.automation.service"):
        await seed_builtin_rules()
    names = await _names()
    assert "Mist (no humidifier)" not in names
    assert "Photoperiod — Lights On" not in names
    assert "Heating Trigger" not in names and "Heater (mine)" in names
    assert _warnings(caplog, "Added built-in") == []
    # And it is recorded, so a later boot does not reconsider them.
    await seed_builtin_rules()
    assert await _names() == names


async def test_a_v4_pi_gains_the_built_ins_5_0_added_but_not_a_deleted_one(caplog):
    await _seed_as_release(_V4)
    await _delete("Heat Wave Warning")
    with caplog.at_level("WARNING", logger="app.automation.service"):
        await seed_builtin_rules()
    names = await _names()
    assert ADDED_IN_V5 <= names
    assert {"CO2 Hard Ceiling", "CO2 Floor — Restrict FAE"} <= names
    assert "Heat Wave Warning" not in names
    added = _warnings(caplog, "Added built-in")
    assert len(added) == 1 and "CO2 Hard Ceiling" in added[0]


async def test_a_5_x_pi_with_every_name_5_0_added_deleted_is_still_read_as_5_x():
    # None of the names only 5.0+ seeded is left, but the first seed batch
    # spans 24 ids: more than any older release seeded.
    await _seed_as_release(_V5_0)
    await _delete(*ADDED_IN_V5)
    await seed_builtin_rules()
    assert not ADDED_IN_V5 & await _names()


async def test_a_pi_with_no_built_in_left_gets_none_added(caplog):
    await _seed_as_release(_V4)
    await _delete(*SEEDED_BEFORE_V5)
    await create_rule(AutomationRule.model_validate({
        "name": "My heater", "priority": 9,
        "condition": {"type": "threshold",
                      "threshold": {"sensor": "temp_f", "operator": "lt", "value": 60}},
        "action": {"target": "plug-heater", "state": "on"},
    }))
    with caplog.at_level("WARNING", logger="app.automation.service"):
        await seed_builtin_rules()
    assert await _names() == {"My heater"}
    assert len(_warnings(caplog, "No built-in automation rule is left")) == 1


async def test_a_fresh_pi_gets_every_built_in_once():
    await seed_builtin_rules()
    assert await _names() == set(CURRENT)
    first = await _stored()
    assert len(first) == len(CURRENT)
    await seed_builtin_rules()
    assert await _stored() == first


async def test_a_fresh_pi_does_not_bring_back_a_built_in_the_operator_deleted():
    """What each Pi was offered is recorded at the first seed."""
    await seed_builtin_rules()
    await _delete("CO2 Floor — Restrict FAE")
    await seed_builtin_rules()
    assert "CO2 Floor — Restrict FAE" not in await _names()


# ── Built-ins no release ships any more ─────────────────────────────────────


async def _set_enabled(name: str, enabled: bool) -> None:
    async with get_db() as db:
        await db.execute("UPDATE automation_rules SET enabled = ? WHERE name = ?",
                         (int(enabled), name))
        await db.commit()


async def _enabled(name: str) -> bool:
    return bool(next(r for r in await _stored() if r["name"] == name)["enabled"])


async def test_a_retired_built_in_is_switched_off_once(caplog):
    await _seed_as_release(_V4)
    with caplog.at_level("WARNING", logger="app.automation.service"):
        await seed_builtin_rules()
    for name in RETIRED_BUILTIN_RULES:
        assert not await _enabled(name), name
        assert len(_warnings(caplog, f"Switched off automation rule '{name}'")) == 1
    # The operator wants one back: it stays on across boots.
    await _set_enabled("Light Scene — Fruiting", True)
    await seed_builtin_rules()
    assert await _enabled("Light Scene — Fruiting")


async def test_an_edited_retired_built_in_is_left_running_and_named(caplog):
    await _seed_as_release(_V4)
    async with get_db() as db:
        row = dict(await (await db.execute(
            "SELECT rule_data FROM automation_rules WHERE name = 'Reishi Antler CO2 Restrict FAE'"
        )).fetchone())
        data = json.loads(row["rule_data"])
        data["cooldown_seconds"] = 900
        await db.execute("UPDATE automation_rules SET rule_data = ? "
                         "WHERE name = 'Reishi Antler CO2 Restrict FAE'", (json.dumps(data),))
        await db.commit()
    with caplog.at_level("WARNING", logger="app.automation.service"):
        await seed_builtin_rules()
    assert await _enabled("Reishi Antler CO2 Restrict FAE")
    edited = _warnings(caplog, "no release ships any more, and it was edited")
    assert len(edited) == 1 and "Reishi Antler CO2 Restrict FAE" in edited[0]


# ── What the upgrade changes on the wire ────────────────────────────────────

async def test_an_upgraded_v4_pi_no_longer_vents_colonization(mock_mqtt, quiet_alerts):
    """The 0.2-4.x Emergency CO2 Exhaust (> 3000 ppm in every phase, and a
    life-safety rule to the current engine) and CO2 FAE Trigger (no phase
    scope) drove the exhaust and FAE fans on a colonizing grow bag."""
    await seed_builtins()
    await _seed_as_release(_V4)
    await seed_builtin_rules()
    await start_grow("blue_oyster", "substrate_colonization", container_type="grow_bag")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 8000, "temp_f": 70, "humidity": 95})
    assert [t for t, _ in mock_mqtt if t.endswith(("/cmd/exhaust", "/cmd/fae"))] == []


async def test_an_upgraded_v4_pi_keeps_the_dark_period_dark(mock_mqtt, quiet_alerts):
    """Light Scene — Fruiting re-lit the fruiting scene every hour, the dark
    period included; retired, only Photoperiod — Lights Off speaks at 23:00."""
    await seed_builtins()
    await _seed_as_release(_V4)
    await seed_builtin_rules()
    await start_grow("blue_oyster", "fruiting")
    with clock(local(23)):
        await evaluate_rules("climate-1", {"temp_f": 60, "humidity": 88})
    scenes = [p for t, p in mock_mqtt if t.endswith("/cmd/scene")]
    assert scenes and all(p.get("state") == "off" for p in scenes), scenes
    assert not [p for p in scenes if p.get("scene") == "fruiting_standard"]
