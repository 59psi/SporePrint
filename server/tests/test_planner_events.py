"""Tests for planner events (month-calendar CRUD) — separate from the recommender."""

from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.planner.models import PlannedEventCreate, PlannedEventUpdate
from app.planner.service import (
    create_planned_event,
    get_planned_event,
    list_planned_events,
    update_planned_event,
    delete_planned_event,
)


def _make(**overrides):
    defaults = dict(title="Inoculate CH-01", kind="inoculate", date="2026-07-15")
    defaults.update(overrides)
    return PlannedEventCreate(**defaults)


# ── CRUD ────────────────────────────────────────────────────────


async def test_create_and_get():
    cid = (await create_chamber(ChamberCreate(name="CH")))["id"]
    ev = await create_planned_event(_make(chamber_id=cid, notes="oak pellets"))
    assert ev["id"] is not None
    assert ev["title"] == "Inoculate CH-01"
    assert ev["kind"] == "inoculate"
    assert ev["date"] == "2026-07-15"
    assert ev["chamber_id"] == cid

    fetched = await get_planned_event(ev["id"])
    assert fetched["id"] == ev["id"]


async def test_get_unknown():
    assert await get_planned_event(9999) is None


async def test_list_sorted_by_date():
    await create_planned_event(_make(title="C", date="2026-07-20"))
    await create_planned_event(_make(title="A", date="2026-07-01"))
    await create_planned_event(_make(title="B", date="2026-07-10"))
    events = await list_planned_events()
    assert [e["date"] for e in events] == ["2026-07-01", "2026-07-10", "2026-07-20"]


async def test_list_range_inclusive():
    await create_planned_event(_make(date="2026-06-30"))
    await create_planned_event(_make(date="2026-07-01"))
    await create_planned_event(_make(date="2026-07-31"))
    await create_planned_event(_make(date="2026-08-01"))
    events = await list_planned_events("2026-07-01", "2026-07-31")
    assert [e["date"] for e in events] == ["2026-07-01", "2026-07-31"]


async def test_update_reschedule_date():
    ev = await create_planned_event(_make(date="2026-07-15"))
    updated = await update_planned_event(ev["id"], PlannedEventUpdate(date="2026-07-22"))
    assert updated["date"] == "2026-07-22"
    # Other fields untouched
    assert updated["title"] == "Inoculate CH-01"


async def test_update_preserves_unset_fields():
    ev = await create_planned_event(_make(notes="original"))
    updated = await update_planned_event(ev["id"], PlannedEventUpdate(title="Renamed"))
    assert updated["title"] == "Renamed"
    assert updated["notes"] == "original"


async def test_update_unknown():
    assert await update_planned_event(9999, PlannedEventUpdate(title="x")) is None


async def test_delete():
    ev = await create_planned_event(_make())
    assert await delete_planned_event(ev["id"]) is True
    assert await get_planned_event(ev["id"]) is None


async def test_delete_unknown():
    assert await delete_planned_event(9999) is False


# ── Validation (model level) ────────────────────────────────────


def test_all_kinds_accepted():
    for kind in ("inoculate", "transfer", "harvest-window", "maintenance", "custom"):
        m = PlannedEventCreate(title="t", kind=kind, date="2026-07-15")
        assert m.kind == kind


def test_invalid_kind_rejected():
    import pytest
    with pytest.raises(ValueError):
        PlannedEventCreate(title="t", kind="explode", date="2026-07-15")


def test_invalid_date_rejected():
    import pytest
    with pytest.raises(ValueError):
        PlannedEventCreate(title="t", kind="custom", date="not-a-date")


# ── API endpoints ───────────────────────────────────────────────


def test_events_crud_endpoints(client):
    created = client.post(
        "/api/planner/events",
        json={"title": "Harvest CH-14", "kind": "harvest-window", "date": "2026-07-14"},
    )
    assert created.status_code == 200
    eid = created.json()["id"]

    listed = client.get("/api/planner/events?from=2026-07-01&to=2026-07-31")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    moved = client.put(f"/api/planner/events/{eid}", json={"date": "2026-07-18"})
    assert moved.status_code == 200
    assert moved.json()["date"] == "2026-07-18"

    deleted = client.delete(f"/api/planner/events/{eid}")
    assert deleted.status_code == 200
    assert client.get("/api/planner/events").json() == []


def test_events_range_filter_excludes(client):
    client.post("/api/planner/events", json={"title": "x", "kind": "custom", "date": "2026-05-01"})
    client.post("/api/planner/events", json={"title": "y", "kind": "custom", "date": "2026-07-15"})
    resp = client.get("/api/planner/events?from=2026-07-01&to=2026-07-31")
    assert len(resp.json()) == 1
    assert resp.json()[0]["date"] == "2026-07-15"


def test_create_event_invalid_kind_422(client):
    resp = client.post("/api/planner/events", json={"title": "x", "kind": "boom", "date": "2026-07-15"})
    assert resp.status_code == 422


def test_create_event_invalid_date_422(client):
    resp = client.post("/api/planner/events", json={"title": "x", "kind": "custom", "date": "07/15/2026"})
    assert resp.status_code == 422


def test_update_event_404(client):
    resp = client.put("/api/planner/events/9999", json={"date": "2026-07-20"})
    assert resp.status_code == 404


def test_delete_event_404(client):
    resp = client.delete("/api/planner/events/9999")
    assert resp.status_code == 404


def test_update_event_invalid_kind_422(client):
    created = client.post(
        "/api/planner/events",
        json={"title": "t", "kind": "custom", "date": "2026-07-15"},
    ).json()
    resp = client.put(f"/api/planner/events/{created['id']}", json={"kind": "nope"})
    assert resp.status_code == 422
