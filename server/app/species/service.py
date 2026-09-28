import json

from ..db import get_db
from .models import SpeciesProfile
from .profiles import BUILTIN_PROFILES, species_id_candidates


class BuiltinProfileReadOnly(Exception):
    """A built-in profile can't be edited in place: seed_builtins() rewrites
    built-in rows from BUILTIN_PROFILES on every start, so an in-place edit
    would silently revert. CLAUDE.md §4c: clone it under a new id instead."""

    def __init__(self, profile_id: str):
        super().__init__(
            f"'{profile_id}' is a built-in profile and is read-only; clone it "
            "(POST /api/species with a new id) to customize"
        )
        self.profile_id = profile_id


async def seed_builtins():
    async with get_db() as db:
        for profile in BUILTIN_PROFILES:
            # Refresh built-in rows only. A user's own (is_builtin = 0) profile
            # that happens to share an id with a built-in is never overwritten.
            await db.execute(
                """INSERT INTO species_profiles (id, data, is_builtin)
                   VALUES (?, ?, 1)
                   ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=unixepoch('now')
                   WHERE species_profiles.is_builtin = 1""",
                (profile.id, profile.model_dump_json()),
            )
        await db.commit()


async def get_all_profiles() -> list[SpeciesProfile]:
    async with get_db() as db:
        cursor = await db.execute("SELECT id, data FROM species_profiles ORDER BY id")
        rows = await cursor.fetchall()
        return [SpeciesProfile.model_validate_json(row["data"]) for row in rows]


async def _find_row(db, profile_id: str):
    """(stored id, is_builtin) for a profile id in either separator spelling."""
    for candidate in species_id_candidates(profile_id):
        cursor = await db.execute(
            "SELECT id, is_builtin FROM species_profiles WHERE id = ?", (candidate,)
        )
        row = await cursor.fetchone()
        if row:
            return row
    return None


async def get_profile(profile_id: str) -> SpeciesProfile | None:
    # Resolve tolerantly across the hyphen/underscore drift (see
    # species_id_candidates): the UI stores hyphenated ids while this table is
    # seeded with the underscored builtin ids. Exact match wins; the swapped
    # variant is the fallback.
    async with get_db() as db:
        for candidate in species_id_candidates(profile_id):
            cursor = await db.execute(
                "SELECT data FROM species_profiles WHERE id = ?", (candidate,)
            )
            row = await cursor.fetchone()
            if row:
                return SpeciesProfile.model_validate_json(row["data"])
        return None


async def create_profile(profile: SpeciesProfile) -> SpeciesProfile:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO species_profiles (id, data, is_builtin) VALUES (?, ?, 0)",
            (profile.id, profile.model_dump_json()),
        )
        await db.commit()
    return profile


async def update_profile(profile_id: str, profile: SpeciesProfile) -> SpeciesProfile | None:
    """Replace a custom profile. None if unknown; raises BuiltinProfileReadOnly
    for a built-in."""
    async with get_db() as db:
        row = await _find_row(db, profile_id)
        if not row:
            return None
        if row["is_builtin"]:
            raise BuiltinProfileReadOnly(row["id"])
        await db.execute(
            "UPDATE species_profiles SET data = ?, updated_at = unixepoch('now') WHERE id = ?",
            (profile.model_dump_json(), row["id"]),
        )
        await db.commit()
    return profile


async def delete_profile(profile_id: str) -> bool:
    async with get_db() as db:
        row = await _find_row(db, profile_id)
        if not row or row["is_builtin"]:
            return False
        await db.execute("DELETE FROM species_profiles WHERE id = ?", (row["id"],))
        await db.commit()
    return True
