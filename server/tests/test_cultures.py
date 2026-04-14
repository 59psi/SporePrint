from app.cultures.models import CultureCreate, CultureUpdate
from app.cultures.service import (
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
        species_profile_id="cubensis_golden_teacher",
        source="vendor",
    )
    defaults.update(overrides)
    return CultureCreate(**defaults)


# ── Full CRUD + lineage ─────────────────────────────────────────


async def test_create_root_culture():
    c = await create_culture(_make_culture())
    assert c["id"] is not None
    assert c["generation"] == 0
    assert c["status"] == "active"
    assert c["type"] == "spore_syringe"


async def test_create_child_inherits_generation():
    root = await create_culture(_make_culture())
    child = await create_culture(_make_culture(
        type="agar", source="transfer", parent_id=root["id"],
    ))
    assert child["generation"] == 1
    assert child["parent_id"] == root["id"]


async def test_create_grandchild_generation():
    root = await create_culture(_make_culture())
    child = await create_culture(_make_culture(
        type="agar", source="transfer", parent_id=root["id"],
    ))
    grandchild = await create_culture(_make_culture(
        type="grain_spawn", source="transfer", parent_id=child["id"],
    ))
    assert grandchild["generation"] == 2


async def test_list_cultures():
    await create_culture(_make_culture())
    await create_culture(_make_culture(type="agar"))
    cultures = await list_cultures()
    assert len(cultures) == 2


async def test_list_cultures_filter_species():
    await create_culture(_make_culture())
    await create_culture(_make_culture(species_profile_id="blue_oyster"))
    result = await list_cultures(species_id="blue_oyster")
    assert len(result) == 1
    assert result[0]["species_profile_id"] == "blue_oyster"


async def test_list_cultures_filter_status():
    c = await create_culture(_make_culture())
    await update_culture(c["id"], CultureUpdate(status="contaminated"))
    await create_culture(_make_culture())
    active = await list_cultures(status="active")
    assert len(active) == 1


async def test_get_culture():
    c = await create_culture(_make_culture())
    fetched = await get_culture(c["id"])
    assert fetched["id"] == c["id"]


async def test_get_culture_not_found():
    result = await get_culture(9999)
    assert result is None


async def test_update_culture_status():
    c = await create_culture(_make_culture())
    updated = await update_culture(c["id"], CultureUpdate(status="contaminated"))
    assert updated["status"] == "contaminated"


async def test_update_culture_preserves_existing():
    c = await create_culture(_make_culture(notes="initial notes"))
    updated = await update_culture(c["id"], CultureUpdate(status="depleted"))
    assert updated["status"] == "depleted"
    assert updated["notes"] == "initial notes"


async def test_update_culture_not_found():
    result = await update_culture(9999, CultureUpdate(status="archived"))
    assert result is None


async def test_delete_culture():
    c = await create_culture(_make_culture())
    assert await delete_culture(c["id"]) is True
    assert await get_culture(c["id"]) is None


async def test_delete_culture_not_found():
    assert await delete_culture(9999) is False


async def test_lineage_tree():
    root = await create_culture(_make_culture(vendor_name="SporeWorks"))
    child1 = await create_culture(_make_culture(
        type="agar", source="transfer", parent_id=root["id"],
    ))
    child2 = await create_culture(_make_culture(
        type="liquid_culture", source="transfer", parent_id=root["id"],
    ))
    grandchild = await create_culture(_make_culture(
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


async def test_lineage_tree_not_found():
    result = await get_lineage_tree(9999)
    assert result is None


# ── Spore print fields ──────────────────────────────────────────


async def test_spore_print_fields():
    c = await create_culture(_make_culture(
        type="spore_print",
        source="clone",
        spore_print_quality="excellent",
        storage_location="fridge shelf 2",
    ))
    assert c["type"] == "spore_print"
    assert c["spore_print_quality"] == "excellent"
    assert c["storage_location"] == "fridge shelf 2"


async def test_update_spore_print_quality():
    c = await create_culture(_make_culture(
        type="spore_print", source="clone", spore_print_quality="good",
    ))
    updated = await update_culture(c["id"], CultureUpdate(spore_print_quality="fair"))
    assert updated["spore_print_quality"] == "fair"


# ── Tissue clone fields ─────────────────────────────────────────


async def test_tissue_clone_fields():
    c = await create_culture(_make_culture(
        type="tissue_clone",
        source="clone",
        tissue_source_location="cap center",
    ))
    assert c["type"] == "tissue_clone"
    assert c["tissue_source_location"] == "cap center"


# ── Contamination rate calculation ───────────────────────────────


async def test_contamination_rate():
    root = await create_culture(_make_culture())
    c1 = await create_culture(_make_culture(
        type="agar", source="transfer", parent_id=root["id"],
    ))
    c2 = await create_culture(_make_culture(
        type="agar", source="transfer", parent_id=root["id"],
    ))
    c3 = await create_culture(_make_culture(
        type="agar", source="transfer", parent_id=root["id"],
    ))

    # Mark one child contaminated
    await update_culture(c1["id"], CultureUpdate(status="contaminated"))

    tree = await get_lineage_tree(root["id"])
    assert tree["total_children"] == 3
    assert tree["contaminated_children"] == 1
    assert tree["contamination_rate"] == 33.3


async def test_contamination_rate_all_clean():
    root = await create_culture(_make_culture())
    await create_culture(_make_culture(
        type="agar", source="transfer", parent_id=root["id"],
    ))
    await create_culture(_make_culture(
        type="agar", source="transfer", parent_id=root["id"],
    ))

    tree = await get_lineage_tree(root["id"])
    assert tree["contamination_rate"] == 0.0


async def test_contamination_rate_no_children():
    root = await create_culture(_make_culture())
    tree = await get_lineage_tree(root["id"])
    assert tree["contamination_rate"] == 0.0
    assert tree["total_children"] == 0
