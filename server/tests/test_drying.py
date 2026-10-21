"""Tests for the harvest drying tracker."""

import csv
import io

import app.sessions.service as sessions_service
from app.sessions.models import SessionCreate, HarvestCreate
from app.sessions.service import (
    create_session,
    add_harvest,
    add_drying_log,
    generate_session_report_csv,
    generate_session_report_md,
    get_drying_progress,
    get_session,
    get_session_stats,
)


def _make_session(**overrides):
    defaults = dict(name="Drying Test", species_profile_id="blue_oyster")
    defaults.update(overrides)
    return SessionCreate(**defaults)


# ── Drying progress (service layer) ─────────────────────────────


async def test_drying_progress_follows_each_weighing_to_cracker_dry():
    s = await create_session(_make_session())
    h = await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0))

    # Before any weighing the harvest is at its fresh weight.
    fresh = await get_drying_progress(s["id"], h["id"])
    assert (fresh["harvest_id"], fresh["flush_number"], fresh["fresh_weight_g"]) == (h["id"], 1, 200.0)
    assert (fresh["current_weight_g"], fresh["moisture_loss_pct"], fresh["target_reached"], fresh["entries"]) == (
        200.0, 0.0, False, [])

    # 200 → 150 → 50 → 18 g
    for grams, loss, reached in ((150.0, 25.0, False), (50.0, 75.0, False), (18.0, 91.0, True)):
        p = await add_drying_log(s["id"], h["id"], grams)
        assert (p["current_weight_g"], p["moisture_loss_pct"], p["target_reached"]) == (grams, loss, reached)
    assert p["dry_wet_ratio"] == 0.09  # 91 % moisture loss: cracker dry
    progress = await get_drying_progress(s["id"], h["id"])
    assert [e["weight_g"] for e in progress["entries"]] == [150.0, 50.0, 18.0]
    assert progress["current_weight_g"] == 18.0


async def test_a_harvest_that_is_unknown_or_another_sessions_is_not_found():
    s1 = await create_session(_make_session(name="Session 1"))
    s2 = await create_session(_make_session(name="Session 2"))
    h = await add_harvest(s1["id"], HarvestCreate(flush_number=1, wet_weight_g=100.0))
    for session_id, harvest_id in ((s1["id"], 99999), (s2["id"], h["id"])):
        assert await add_drying_log(session_id, harvest_id, 50.0) is None
        assert await get_drying_progress(session_id, harvest_id) is None
    assert (await get_drying_progress(s1["id"], h["id"]))["entries"] == []


# ── HTTP endpoint tests ─────────────────────────────────────────


def test_drying_log_endpoint(client):
    # Create session + harvest
    r = client.post("/api/sessions", json={
        "name": "Drying API Test",
        "species_profile_id": "blue_oyster",
    })
    session_id = r.json()["id"]

    r = client.post(f"/api/sessions/{session_id}/harvest", json={
        "flush_number": 1, "wet_weight_g": 200.0,
    })
    harvest_id = r.json()["id"]

    # POST drying log entry
    r = client.post(
        f"/api/sessions/{session_id}/harvest/{harvest_id}/drying-log",
        json={"weight_g": 150.0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["current_weight_g"] == 150.0
    assert data["moisture_loss_pct"] == 25.0

    # GET drying progress
    r = client.get(f"/api/sessions/{session_id}/harvest/{harvest_id}/drying")
    assert r.status_code == 200
    data = r.json()
    assert data["current_weight_g"] == 150.0
    assert len(data["entries"]) == 1


# ── Drying-complete notice goes out once per harvest ─────────────


async def test_drying_complete_notifies_once_per_harvest_through_the_modules_notifier(monkeypatch):
    """add_drying_log re-imported notify_info inside the function, so the
    notifier the module holds (the one a test or a caller patches) was
    bypassed. Each harvest's notice carries its own dedup key, so a second
    weighing of the same harvest is deduplicated, another harvest's is not."""
    sent = []

    async def fake_notify_info(title, message, dedup_key=None):
        sent.append((title, dedup_key))

    monkeypatch.setattr(sessions_service, "notify_info", fake_notify_info)
    s = await create_session(_make_session())
    h1 = await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0))
    h2 = await add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=200.0))
    await add_drying_log(s["id"], h1["id"], 18.0)
    await add_drying_log(s["id"], h1["id"], 17.0)
    await add_drying_log(s["id"], h2["id"], 18.0)
    assert sent == [("Drying Complete — Drying Test", f"drying:{h1['id']}"),
                    ("Drying Complete — Drying Test", f"drying:{h1['id']}"),
                    ("Drying Complete — Drying Test", f"drying:{h2['id']}")]


# ── the dried weight is the harvest's dry yield ──────────────────


async def test_reaching_cracker_dry_records_the_dry_yield(monkeypatch):
    """A 400 g harvest dried to 38 g read 'Drying Complete' while the dry
    yield stayed 0 g in the stats, the report, the CSV and the cloud."""
    changed = []

    async def _listener(session_id):
        changed.append(session_id)

    monkeypatch.setattr(sessions_service, "_session_change_listeners", [_listener])
    s = await create_session(_make_session())
    h = await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=400.0))
    for grams in (250.0, 120.0):  # not dry yet: nothing recorded
        await add_drying_log(s["id"], h["id"], grams)
    assert (await get_session(s["id"]))["total_dry_yield_g"] == 0
    changed.clear()
    await add_drying_log(s["id"], h["id"], 38.0)
    assert changed == [s["id"]]  # the cloud sync hears of it
    assert (await get_session(s["id"]))["total_dry_yield_g"] == 38.0
    # A later weighing past the target replaces it, never adds to it.
    await add_drying_log(s["id"], h["id"], 36.0)
    assert (await get_session(s["id"]))["total_dry_yield_g"] == 36.0
    assert (await get_session_stats(s["id"]))["total_dry_yield_g"] == 36.0
    rows = list(csv.DictReader(io.StringIO(await generate_session_report_csv(s["id"]))))
    assert rows[0]["dry_weight_g"] == "36.0"
    assert "| Total Dry Yield | 36.0g |" in await generate_session_report_md(s["id"])


async def test_a_dry_weight_given_at_harvest_is_not_counted_twice():
    s = await create_session(_make_session())
    h1 = await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=400.0, dry_weight_g=40.0))
    h2 = await add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=200.0))
    await add_drying_log(s["id"], h2["id"], 19.0)
    assert (await get_session(s["id"]))["total_dry_yield_g"] == 59.0
    await add_drying_log(s["id"], h1["id"], 38.0)  # re-weighed: replaces 40
    assert (await get_session(s["id"]))["total_dry_yield_g"] == 57.0
