from app.chambers.models import ChamberCreate, ChamberUpdate
from app.chambers.service import (
    create_chamber,
    get_chamber,
    list_chambers,
    update_chamber,
    delete_chamber,
)
from app.sessions.models import SessionCreate
from app.sessions.service import create_session


def _make_chamber(**overrides):
    defaults = dict(name="Fruiting Chamber A")
    defaults.update(overrides)
    return ChamberCreate(**defaults)


async def _make_session(name="Test Grow"):
    return await create_session(SessionCreate(
        name=name,
        species_profile_id="cubensis_golden_teacher",
    ))


# ── CRUD ───────────────────────────────────────────────────────


async def test_create_chamber():
    c = await create_chamber(_make_chamber())
    assert c["id"] is not None
    assert c["name"] == "Fruiting Chamber A"
    assert c["node_ids"] == []
    assert c["automation_rule_ids"] == []
    assert c["active_session_id"] is None


async def test_create_chamber_with_nodes():
    c = await create_chamber(_make_chamber(node_ids=["climate-01", "relay-01"]))
    assert c["node_ids"] == ["climate-01", "relay-01"]


async def test_list_chambers():
    await create_chamber(_make_chamber(name="Chamber A"))
    await create_chamber(_make_chamber(name="Chamber B"))
    chambers = await list_chambers()
    assert len(chambers) == 2


async def test_list_chambers_order():
    a = await create_chamber(_make_chamber(name="First"))
    b = await create_chamber(_make_chamber(name="Second"))
    chambers = await list_chambers()
    # Most recent first
    assert chambers[0]["name"] == "Second"
    assert chambers[1]["name"] == "First"


async def test_get_chamber():
    c = await create_chamber(_make_chamber())
    fetched = await get_chamber(c["id"])
    assert fetched["id"] == c["id"]
    assert fetched["name"] == c["name"]


async def test_get_chamber_not_found():
    result = await get_chamber(9999)
    assert result is None


async def test_update_chamber_name():
    c = await create_chamber(_make_chamber())
    updated = await update_chamber(c["id"], ChamberUpdate(name="Renamed"))
    assert updated["name"] == "Renamed"


async def test_update_chamber_nodes():
    c = await create_chamber(_make_chamber(node_ids=["climate-01"]))
    updated = await update_chamber(c["id"], ChamberUpdate(node_ids=["climate-01", "relay-01", "cam-01"]))
    assert updated["node_ids"] == ["climate-01", "relay-01", "cam-01"]


async def test_update_chamber_preserves_existing():
    c = await create_chamber(_make_chamber(
        name="Keep This",
        description="Important chamber",
        node_ids=["climate-01"],
    ))
    updated = await update_chamber(c["id"], ChamberUpdate(automation_rule_ids=[1, 2]))
    assert updated["name"] == "Keep This"
    assert updated["description"] == "Important chamber"
    assert updated["node_ids"] == ["climate-01"]
    assert updated["automation_rule_ids"] == [1, 2]


async def test_update_chamber_not_found():
    result = await update_chamber(9999, ChamberUpdate(name="Nope"))
    assert result is None


async def test_delete_chamber():
    c = await create_chamber(_make_chamber())
    assert await delete_chamber(c["id"]) is True
    assert await get_chamber(c["id"]) is None


async def test_delete_chamber_not_found():
    assert await delete_chamber(9999) is False


# ── Session assignment ─────────────────────────────────────────


async def test_assign_session_to_chamber():
    session = await _make_session()
    c = await create_chamber(_make_chamber())
    updated = await update_chamber(c["id"], ChamberUpdate(active_session_id=session["id"]))
    assert updated["active_session_id"] == session["id"]


async def test_reassign_session():
    s1 = await _make_session("Grow 1")
    s2 = await _make_session("Grow 2")
    c = await create_chamber(_make_chamber())
    await update_chamber(c["id"], ChamberUpdate(active_session_id=s1["id"]))
    updated = await update_chamber(c["id"], ChamberUpdate(active_session_id=s2["id"]))
    assert updated["active_session_id"] == s2["id"]
