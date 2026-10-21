import pytest

from app.db import get_db
from app.species.service import seed_builtins
from app.cultures.models import CultureCreate, CultureUpdate
from app.cultures.service import (
    CultureHasDescendants,
    ParentCultureNotFound,
    create_culture,
    get_culture,
    list_cultures,
    update_culture,
    delete_culture,
    get_lineage_tree,
)


def _make_culture(**overrides):
    defaults = dict(
        type="spore_syringe",
        species_profile_id="blue_oyster",
        source="vendor",
    )
    defaults.update(overrides)
    return CultureCreate(**defaults)


# ── Lineage ─────────────────────────────────────────────────────


async def test_generation_counts_the_transfers_from_the_root():
    root = await create_culture(_make_culture())
    child = await create_culture(_make_culture(type="agar", source="transfer", parent_id=root["id"]))
    grandchild = await create_culture(_make_culture(
        type="grain_spawn", source="transfer", parent_id=child["id"]))
    assert (root["generation"], root["status"], root["type"], root["parent_id"]) == (
        0, "active", "spore_syringe", None)
    assert (child["generation"], child["parent_id"]) == (1, root["id"])
    assert (grandchild["generation"], grandchild["parent_id"]) == (2, child["id"])


async def test_lineage_tree():
    root = await create_culture(_make_culture(vendor_name="SporeWorks"))
    child1 = await create_culture(_make_culture(
        type="agar", source="transfer", parent_id=root["id"],
    ))
    await create_culture(_make_culture(
        type="liquid_culture", source="transfer", parent_id=root["id"],
    ))
    await create_culture(_make_culture(
        type="grain_spawn", source="transfer", parent_id=child1["id"],
    ))

    tree = await get_lineage_tree(root["id"])
    assert tree is not None
    assert tree["culture"]["id"] == root["id"]
    assert len(tree["ancestors"]) == 0
    assert len(tree["descendants"]) == 3
    assert tree["contamination_rate"] == 0.0
    assert tree["total_children"] == 2


async def test_lineage_tree_from_child():
    root = await create_culture(_make_culture())
    child = await create_culture(_make_culture(
        type="agar", source="transfer", parent_id=root["id"],
    ))
    grandchild = await create_culture(_make_culture(
        type="grain_spawn", source="transfer", parent_id=child["id"],
    ))

    tree = await get_lineage_tree(child["id"])
    assert len(tree["ancestors"]) == 1
    assert tree["ancestors"][0]["id"] == root["id"]
    assert len(tree["descendants"]) == 1
    assert tree["descendants"][0]["id"] == grandchild["id"]


@pytest.mark.parametrize(("children", "contaminated", "rate"), [(3, 1, 33.3), (0, 0, 0.0)],
                         ids=["one-of-three", "no-children"])
async def test_contamination_rate_of_a_cultures_children(children, contaminated, rate):
    root = await create_culture(_make_culture())
    for i in range(children):
        child = await create_culture(_make_culture(type="agar", source="transfer", parent_id=root["id"]))
        if i < contaminated:
            await update_culture(child["id"], CultureUpdate(status="contaminated"))

    tree = await get_lineage_tree(root["id"])
    assert (tree["total_children"], tree["contaminated_children"], tree["contamination_rate"]) == (
        children, contaminated, rate)


# ── Fields and filters ──────────────────────────────────────────


async def test_type_specific_fields_persist_and_an_update_keeps_what_it_omits():
    """Spore print and tissue clone details are stored on create; a partial
    update changes only the fields it names."""
    sp = await create_culture(_make_culture(
        type="spore_print", source="clone", spore_print_quality="excellent",
        storage_location="fridge shelf 2", notes="initial notes"))
    assert (sp["spore_print_quality"], sp["storage_location"]) == ("excellent", "fridge shelf 2")
    updated = await update_culture(sp["id"], CultureUpdate(spore_print_quality="fair"))
    assert (updated["spore_print_quality"], updated["storage_location"], updated["notes"], updated["status"]) == (
        "fair", "fridge shelf 2", "initial notes", "active")
    updated = await update_culture(sp["id"], CultureUpdate(status="depleted"))
    assert (updated["status"], updated["spore_print_quality"]) == ("depleted", "fair")

    clone = await create_culture(_make_culture(
        type="tissue_clone", source="clone", tissue_source_location="cap center"))
    assert (await get_culture(clone["id"]))["tissue_source_location"] == "cap center"


async def test_species_filter_finds_every_spelling():
    """A culture posted as 'lions_mane' was stored verbatim and the dashboard's
    'lions-mane' filter missed it; an older 'lions-mane' row the reverse."""
    await seed_builtins()
    posted = await create_culture(_make_culture(species_profile_id="lions_mane"))
    assert posted["species_profile_id"] == "lions-mane"
    async with get_db() as db:
        await db.execute(
            "INSERT INTO cultures (type, species_profile_id, source) VALUES ('agar', 'lions_mane', 'vendor')")
        await db.commit()
    for spelling in ("lions_mane", "lions-mane"):
        assert len(await list_cultures(species_id=spelling)) == 2, spelling
    assert len(await list_cultures(species_id="blue_oyster")) == 0


async def test_list_cultures_filter_status():
    c = await create_culture(_make_culture())
    await update_culture(c["id"], CultureUpdate(status="contaminated"))
    await create_culture(_make_culture())
    assert len(await list_cultures()) == 2
    active = await list_cultures(status="active")
    assert len(active) == 1


# ── FK violations surface as client errors, not 500s ────────────────


async def test_delete_culture_with_children_is_refused():
    root = await create_culture(_make_culture())
    await create_culture(_make_culture(type="agar", source="transfer", parent_id=root["id"]))
    with pytest.raises(CultureHasDescendants) as exc:
        await delete_culture(root["id"])
    assert exc.value.count == 1
    assert await get_culture(root["id"]) is not None


async def test_delete_leaf_culture_still_works():
    root = await create_culture(_make_culture())
    child = await create_culture(_make_culture(type="agar", source="transfer", parent_id=root["id"]))
    assert await delete_culture(child["id"]) is True
    assert await delete_culture(root["id"]) is True
    assert await get_culture(root["id"]) is None


async def test_create_culture_with_unknown_parent_is_refused():
    with pytest.raises(ParentCultureNotFound):
        await create_culture(_make_culture(source="transfer", parent_id=9999))


def test_culture_routes(client):
    """The routes over the service: create, the species filter by either
    spelling, read, patch, lineage and delete, with a 404 for an unknown
    culture, a 409 for one with children and a 400 for an unknown parent."""
    body = {"type": "agar", "species_profile_id": "blue_oyster", "source": "vendor"}
    root = client.post("/api/cultures", json=body).json()
    child = client.post("/api/cultures", json={
        **body, "type": "grain_spawn", "source": "transfer", "parent_id": root["id"]}).json()
    listed = client.get("/api/cultures", params={"species": "blue-oyster"}).json()
    assert {c["id"] for c in listed} == {root["id"], child["id"]}
    assert client.get(f"/api/cultures/{root['id']}").json()["generation"] == 0
    assert client.patch(f"/api/cultures/{child['id']}", json={"status": "contaminated"}).json()["status"] == (
        "contaminated")
    assert client.get("/api/cultures", params={"status": "active"}).json()[0]["id"] == root["id"]
    assert client.get(f"/api/cultures/{root['id']}/lineage").json()["contaminated_children"] == 1

    r = client.delete(f"/api/cultures/{root['id']}")
    assert r.status_code == 409 and "archive" in r.json()["detail"].lower()
    r = client.post("/api/cultures", json={**body, "source": "transfer", "parent_id": 424242})
    assert r.status_code == 400
    assert client.delete(f"/api/cultures/{child['id']}").json() == {"deleted": True}

    for method, path, payload in (("GET", "/api/cultures/9999", None),
                                  ("PATCH", "/api/cultures/9999", {"status": "archived"}),
                                  ("DELETE", "/api/cultures/9999", None),
                                  ("GET", "/api/cultures/9999/lineage", None)):
        assert client.request(method, path, json=payload).status_code == 404, (method, path)
