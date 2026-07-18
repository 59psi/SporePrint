import json

from ..db import get_db
from .models import SpeciesProfile
from .profiles import BUILTIN_PROFILES, species_id_candidates


async def seed_builtins():
    async with get_db() as db:
        for profile in BUILTIN_PROFILES:
            await db.execute(
                """INSERT INTO species_profiles (id, data, is_builtin)
                   VALUES (?, ?, 1)
                   ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=unixepoch('now')""",
                (profile.id, profile.model_dump_json()),
            )
        await db.commit()


async def get_all_profiles() -> list[SpeciesProfile]:
    async with get_db() as db:
        cursor = await db.execute("SELECT id, data FROM species_profiles ORDER BY id")
        rows = await cursor.fetchall()
        return [SpeciesProfile.model_validate_json(row["data"]) for row in rows]


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
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT is_builtin FROM species_profiles WHERE id = ?", (profile_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        await db.execute(
            "UPDATE species_profiles SET data = ?, updated_at = unixepoch('now') WHERE id = ?",
            (profile.model_dump_json(), profile_id),
        )
        await db.commit()
    return profile


async def delete_profile(profile_id: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT is_builtin FROM species_profiles WHERE id = ?", (profile_id,)
        )
        row = await cursor.fetchone()
        if not row or row["is_builtin"]:
            return False
        await db.execute("DELETE FROM species_profiles WHERE id = ?", (profile_id,))
        await db.commit()
    return True
