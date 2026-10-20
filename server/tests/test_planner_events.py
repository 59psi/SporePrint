"""Tests for planner events (month-calendar CRUD) — separate from the recommender."""

import pytest

from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.planner.models import PlannedEventCreate, PlannedEventUpdate
from app.planner.service import (
    create_planned_event,
    get_planned_event,
    list_planned_events,
    update_planned_event,
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
    assert (ev["title"], ev["kind"], ev["date"], ev["chamber_id"], ev["notes"]) == (
        "Inoculate CH-01", "inoculate", "2026-07-15", cid, "oak pellets")
    assert await get_planned_event(ev["id"]) == ev


async def test_list_is_sorted_by_date_and_its_range_is_inclusive():
    for date in ("2026-07-20", "2026-06-30", "2026-07-01", "2026-08-01", "2026-07-31"):
        await create_planned_event(_make(date=date))
    assert [e["date"] for e in await list_planned_events()] == [
        "2026-06-30", "2026-07-01", "2026-07-20", "2026-07-31", "2026-08-01"]
    assert [e["date"] for e in await list_planned_events("2026-07-01", "2026-07-31")] == [
        "2026-07-01", "2026-07-20", "2026-07-31"]


async def test_an_update_changes_only_the_fields_it_names():
    ev = await create_planned_event(_make(notes="original"))
    moved = await update_planned_event(ev["id"], PlannedEventUpdate(date="2026-07-22"))  # drag-reschedule
    assert (moved["date"], moved["title"], moved["notes"]) == ("2026-07-22", "Inoculate CH-01", "original")
    renamed = await update_planned_event(ev["id"], PlannedEventUpdate(title="Renamed"))
    assert (renamed["title"], renamed["date"], renamed["notes"]) == ("Renamed", "2026-07-22", "original")


# ── Validation ──────────────────────────────────────────────────


def test_only_the_planner_kinds_and_iso_dates_are_accepted():
    for kind in ("inoculate", "transfer", "harvest-window", "maintenance", "custom"):
        assert PlannedEventCreate(title="t", kind=kind, date="2026-07-15").kind == kind
    with pytest.raises(ValueError):
        PlannedEventCreate(title="t", kind="explode", date="2026-07-15")
    with pytest.raises(ValueError):
        PlannedEventCreate(title="t", kind="custom", date="not-a-date")


def test_a_bad_kind_or_date_is_422_on_create_and_update(client):
    assert client.post("/api/planner/events",
                       json={"title": "x", "kind": "boom", "date": "2026-07-15"}).status_code == 422
    assert client.post("/api/planner/events",
                       json={"title": "x", "kind": "custom", "date": "07/15/2026"}).status_code == 422
    created = client.post("/api/planner/events",
                          json={"title": "t", "kind": "custom", "date": "2026-07-15"}).json()
    assert client.put(f"/api/planner/events/{created['id']}", json={"kind": "nope"}).status_code == 422
    assert client.get("/api/planner/events").json()[0]["kind"] == "custom"


# ── API endpoints ───────────────────────────────────────────────


def test_events_crud_endpoints(client):
    created = client.post(
        "/api/planner/events",
        json={"title": "Harvest CH-14", "kind": "harvest-window", "date": "2026-07-14"},
    )
    assert created.status_code == 200
    eid = created.json()["id"]
    client.post("/api/planner/events", json={"title": "x", "kind": "custom", "date": "2026-05-01"})

    listed = client.get("/api/planner/events?from=2026-07-01&to=2026-07-31")
    assert listed.status_code == 200
    assert [e["id"] for e in listed.json()] == [eid]

    moved = client.put(f"/api/planner/events/{eid}", json={"date": "2026-07-18"})
    assert moved.status_code == 200
    assert moved.json()["date"] == "2026-07-18"

    deleted = client.delete(f"/api/planner/events/{eid}")
    assert deleted.status_code == 200
    assert [e["title"] for e in client.get("/api/planner/events").json()] == ["x"]


def test_an_unknown_event_is_404(client):
    assert client.put("/api/planner/events/9999", json={"date": "2026-07-20"}).status_code == 404
    assert client.delete("/api/planner/events/9999").status_code == 404


# ── Stored dates are canonical ──────────────────────────────────


async def test_other_iso_spellings_are_stored_as_calendar_dates():
    """date.fromisoformat takes '20261016' and '2026-W42-5' too; stored as
    sent they sorted outside every month's text range and never showed."""
    basic = await create_planned_event(_make(date="20261016"))
    week = await create_planned_event(_make(date="2026-W42-5"))
    assert basic["date"] == week["date"] == "2026-10-16"
    listed = await list_planned_events("2026-10-01", "2026-10-31")
    assert sorted(e["id"] for e in listed) == sorted([basic["id"], week["id"]])
    moved = await update_planned_event(basic["id"], PlannedEventUpdate(date="20261020"))
    assert moved["date"] == "2026-10-20"


# ── Unknown chamber / session references ────────────────────────


def test_unknown_references_are_422_not_500(client):
    body = {"title": "t", "kind": "custom", "date": "2026-07-15"}
    for ref in ({"chamber_id": 9999}, {"session_id": 9999}):
        resp = client.post("/api/planner/events", json={**body, **ref})
        assert resp.status_code == 422, resp.text  # was a FOREIGN KEY 500
        assert "9999" in resp.json()["detail"]
    created = client.post("/api/planner/events", json=body).json()
    resp = client.put(f"/api/planner/events/{created['id']}", json={"session_id": 9999})
    assert resp.status_code == 422
    assert client.get("/api/planner/events").json()[0]["session_id"] is None
