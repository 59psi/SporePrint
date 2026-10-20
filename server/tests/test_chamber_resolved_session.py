"""GET /api/chambers and /api/chambers/{id} report `resolved_session_id`: the
grow the Pi runs in each chamber, by the per-node session rule the automation
engine drives the chamber's nodes with (get_active_session_for_chambers).
The chamber's `active_session_id` is only one link to a grow, so a dashboard
reading it alone showed a chamber as idle while its nodes ran a grow."""

import time

from app.chambers.models import ChamberCreate
from app.chambers.router import get_chamber as get_chamber_route
from app.chambers.router import list_chambers as list_chambers_route
from app.chambers.service import create_chamber
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session, get_active_session_for_chambers


async def _insert_active_session(name: str, chamber_id: int | None, created_at: float) -> int:
    """An active grow row bound to `chamber_id` (written directly, so the
    chamber's link is left as the test sets it)."""
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO sessions (name, species_profile_id, current_phase, status, chamber_id, created_at) "
            "VALUES (?, 'blue-oyster', 'fruiting', 'active', ?, ?)",
            (name, chamber_id, created_at),
        )
        await db.commit()
        return cursor.lastrowid


async def test_a_grow_bound_to_no_chamber_is_the_idle_chambers_grow():
    """A grow started without a chamber (the Sessions form's "unassigned",
    the API, a cloud session_start) runs every chamber with no grow of its
    own: the chamber is not idle."""
    chamber = await create_chamber(ChamberCreate(name="Closet", node_ids=["climate-01"]))
    grow = await create_session(SessionCreate(name="Closet run", species_profile_id="blue_oyster"))

    shown = await get_chamber_route(chamber["id"])
    assert shown["active_session_id"] is None
    assert shown["resolved_session_id"] == grow["id"]
    resolved = await get_active_session_for_chambers([chamber["id"]])
    assert resolved is not None and resolved["id"] == shown["resolved_session_id"]


async def test_the_older_grow_still_shows_after_the_linked_one_ends():
    """Two tubs bound to one chamber; the newer (linked) one ends, which
    clears the link while the older one keeps running in the chamber."""
    chamber = await create_chamber(ChamberCreate(name="Rack", node_ids=["climate-01"]))
    now = time.time()
    older = await _insert_active_session("Tub A", chamber["id"], now - 3600)
    newer = await _insert_active_session("Tub B", chamber["id"], now)
    async with get_db() as db:
        await db.execute("UPDATE sessions SET status = 'completed' WHERE id = ?", (newer,))
        await db.execute("UPDATE chambers SET active_session_id = NULL WHERE id = ?", (chamber["id"],))
        await db.commit()

    (listed,) = await list_chambers_route()
    assert listed["active_session_id"] is None
    assert listed["resolved_session_id"] == older


async def test_an_idle_chamber_resolves_to_none_and_keeps_its_link_field():
    chamber = await create_chamber(ChamberCreate(name="Spare"))
    other = await create_chamber(ChamberCreate(name="Busy"))
    await create_session(SessionCreate(
        name="Busy run", species_profile_id="blue_oyster", chamber_id=other["id"],
    ))

    by_id = {c["id"]: c for c in await list_chambers_route()}
    assert by_id[chamber["id"]]["resolved_session_id"] is None
    assert by_id[chamber["id"]]["active_session_id"] is None
    # The busy chamber's own grow, which its link also names.
    assert by_id[other["id"]]["resolved_session_id"] == by_id[other["id"]]["active_session_id"]


def test_the_routes_send_the_field(client):
    chamber = client.post("/api/chambers", json={"name": "Closet"}).json()
    grow = client.post("/api/sessions", json={"name": "G", "species_profile_id": "blue_oyster"}).json()
    one = client.get(f"/api/chambers/{chamber['id']}").json()
    assert one["resolved_session_id"] == grow["id"]
    assert one["active_session_id"] is None
    (listed,) = client.get("/api/chambers").json()
    assert listed["resolved_session_id"] == grow["id"]
