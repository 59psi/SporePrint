import time

from ..db import get_db
from .models import CultureCreate, CultureUpdate


async def create_culture(data: CultureCreate) -> dict:
    """Create a culture. Auto-calculates generation from parent chain."""
    generation = 0
    if data.parent_id is not None:
        parent = await get_culture(data.parent_id)
        if parent:
            generation = parent["generation"] + 1

    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO cultures (type, species_profile_id, source, parent_id,
               vendor_name, lot_number, generation, notes, spore_print_quality,
               tissue_source_location, storage_location)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.type, data.species_profile_id, data.source, data.parent_id,
             data.vendor_name, data.lot_number, generation, data.notes,
             data.spore_print_quality, data.tissue_source_location,
             data.storage_location),
        )
        await db.commit()
        culture_id = cursor.lastrowid
    return await get_culture(culture_id)


async def get_culture(culture_id: int) -> dict | None:
    """Fetch a single culture by ID."""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM cultures WHERE id = ?", (culture_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_cultures(species_id: str | None = None, status: str | None = None) -> list[dict]:
    """List cultures with optional filters, ordered by created_at DESC."""
    query = "SELECT * FROM cultures WHERE 1=1"
    params = []
    if species_id:
        query += " AND species_profile_id = ?"
        params.append(species_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC"

    async with get_db() as db:
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]


async def update_culture(culture_id: int, data: CultureUpdate) -> dict | None:
    """Partial update of a culture. Uses COALESCE to keep existing values for NULL fields."""
    existing = await get_culture(culture_id)
    if not existing:
        return None

    dumped = data.model_dump()

    async with get_db() as db:
        await db.execute(
            """UPDATE cultures
               SET status = ?, notes = ?, storage_location = ?, spore_print_quality = ?
               WHERE id = ?""",
            (
                dumped["status"] if dumped["status"] is not None else existing["status"],
                dumped["notes"] if dumped["notes"] is not None else existing["notes"],
                dumped["storage_location"] if dumped["storage_location"] is not None else existing["storage_location"],
                dumped["spore_print_quality"] if dumped["spore_print_quality"] is not None else existing["spore_print_quality"],
                culture_id,
            ),
        )
        await db.commit()
    return await get_culture(culture_id)


async def delete_culture(culture_id: int) -> bool:
    """Delete a culture. Returns True if a row was deleted."""
    async with get_db() as db:
        cursor = await db.execute("DELETE FROM cultures WHERE id = ?", (culture_id,))
        await db.commit()
        return cursor.rowcount > 0


async def get_lineage_tree(culture_id: int) -> dict | None:
    """Build full lineage tree: ancestors up to root + all descendants, with contamination rates."""
    root_culture = await get_culture(culture_id)
    if not root_culture:
        return None

    async with get_db() as db:
        # Walk up to root via parent_id chain
        ancestors = []
        current = root_culture
        while current["parent_id"] is not None:
            cursor = await db.execute("SELECT * FROM cultures WHERE id = ?", (current["parent_id"],))
            row = await cursor.fetchone()
            if not row:
                break
            parent = dict(row)
            ancestors.insert(0, parent)
            current = parent

        # Walk down: get all descendants recursively via iterative BFS
        descendants = await _get_descendants(db, culture_id)

        # Calculate contamination rate for immediate children
        cursor = await db.execute(
            "SELECT * FROM cultures WHERE parent_id = ?", (culture_id,)
        )
        children = [dict(r) for r in await cursor.fetchall()]
        total_children = len(children)
        contaminated_children = sum(1 for c in children if c["status"] == "contaminated")
        contamination_rate = round(
            (contaminated_children / total_children) * 100, 1
        ) if total_children > 0 else 0.0

    return {
        "culture": root_culture,
        "ancestors": ancestors,
        "descendants": descendants,
        "contamination_rate": contamination_rate,
        "total_children": total_children,
        "contaminated_children": contaminated_children,
    }


async def _get_descendants(db, parent_id: int) -> list[dict]:
    """Iterative BFS to collect all descendants of a culture."""
    descendants = []
    queue = [parent_id]

    while queue:
        current_id = queue.pop(0)
        cursor = await db.execute(
            "SELECT * FROM cultures WHERE parent_id = ?", (current_id,)
        )
        children = [dict(r) for r in await cursor.fetchall()]
        for child in children:
            descendants.append(child)
            queue.append(child["id"])

    return descendants
