import logging
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from ..config import settings
from ..db import get_db
from .models import SpeciesProfile, profile_problems
from .profiles import BUILTIN_PROFILES, canonical_species_id, species_id_candidates

log = logging.getLogger(__name__)


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


class InvalidProfileError(ValueError):
    """A profile automation could not run (swapped bands, light hours that do
    not add up to a day, ...: species.models.profile_problems), or a PUT body
    naming another profile than its path (422)."""


class ProfileExistsError(Exception):
    """POST /api/species for an id a stored profile already answers to (409).

    Sessions store the hyphenated spelling of a species id, which finds the
    exact spelling first: a custom 'lions-mane' beside the built-in
    'lions_mane' silently took over every lion's mane grow.
    """

    def __init__(self, profile_id: str, stored_id: str):
        twin = ("" if stored_id == profile_id
                else f" ('{profile_id}' is the same id with its '-' and '_' spelled differently)")
        super().__init__(
            f"Species profile '{stored_id}' already exists{twin}: pick another id, "
            f"or change it with PUT /api/species/{stored_id}"
        )
        self.profile_id = profile_id
        self.stored_id = stored_id


class ProfileInUseError(Exception):
    """DELETE of a custom profile active grows still run on (409): they would
    lose every setpoint and stage alert for the rest of the grow."""

    def __init__(self, profile_id: str, sessions: list[tuple[int, str]]):
        names = ", ".join(f"'{name}' (session {sid})" for sid, name in sessions)
        super().__init__(
            f"Species profile '{profile_id}' is in use by active grow(s) {names}: "
            "complete or abort them before deleting it"
        )
        self.profile_id = profile_id
        self.sessions = sessions


# ── Reading profiles ──────────────────────────────────────────────────
#
# Every stored profile is parsed once and kept: GET /api/species and every
# telemetry frame's get_profile used to re-read and re-validate rows that only
# change here (seed_builtins and the profile CRUD below, each of which drops
# the cache). Keyed by the database file, so it never outlives the database it
# was read from. The profiles are shared between callers: read them, and
# model_copy() one to change it.

@dataclass
class _ProfileCache:
    database: str
    by_id: dict[str, SpeciesProfile]
    listing_json: bytes | None = None


_cache: _ProfileCache | None = None
# Bumped by every write, so a read that began before the write never stores
# what it read.
_generation = 0
_LISTING = TypeAdapter(list[SpeciesProfile])


def _invalidate() -> None:
    global _cache, _generation
    _cache = None
    _generation += 1


async def _profiles() -> _ProfileCache:
    global _cache
    cache = _cache
    if cache is not None and cache.database == settings.database_path:
        return cache
    generation = _generation
    async with get_db() as db:
        cursor = await db.execute("SELECT id, data FROM species_profiles ORDER BY id")
        rows = await cursor.fetchall()
    by_id: dict[str, SpeciesProfile] = {}
    for row in rows:
        try:
            by_id[row["id"]] = SpeciesProfile.model_validate_json(row["data"])
        except ValidationError as e:
            # One unreadable row must not take every other profile down with it.
            log.warning("Species profile %r is unreadable and is skipped: %s", row["id"], e)
    cache = _ProfileCache(settings.database_path, by_id)
    if generation == _generation:
        _cache = cache
    return cache


def _match(stored_ids: Collection[str], profile_id: str) -> str | None:
    """The stored id `profile_id` names, or None.

    Exactly as given first, then with '-' and '_' swapped
    (species_id_candidates): the UI stores hyphenated ids while the built-ins
    are seeded underscored. Last, the id that reads the same with every '_' as
    '-': sessions used to store a custom 'lions_mane-custom' as
    'lions-mane-custom', which neither of the first two finds. Of several such
    ids, the first in sort order.
    """
    for candidate in species_id_candidates(profile_id):
        if candidate in stored_ids:
            return candidate
    canonical = canonical_species_id(profile_id)
    same = sorted(s for s in stored_ids if canonical_species_id(s) == canonical)
    return same[0] if same else None


async def get_all_profiles() -> list[SpeciesProfile]:
    """Every profile, by id."""
    return list((await _profiles()).by_id.values())


async def profiles_listing_json() -> bytes:
    """GET /api/species's body: get_all_profiles() as JSON, rendered once per
    change instead of on every request."""
    cache = await _profiles()
    if cache.listing_json is None:
        cache.listing_json = _LISTING.dump_json(list(cache.by_id.values()))
    return cache.listing_json


async def get_profile(profile_id: str) -> SpeciesProfile | None:
    """The profile `profile_id` names in any separator spelling (_match), or None."""
    cache = await _profiles()
    stored = _match(cache.by_id, profile_id)
    return cache.by_id[stored] if stored is not None else None


async def stored_species_id(requested: str) -> str:
    """The species id a session or culture records for `requested`.

    The hyphenated spelling (canonical_species_id: what the cloud and the
    dashboards send and match on) whenever it finds the same profile again;
    else the profile's own id, so a custom 'my_strain' beside a custom
    'my-strain' keeps pointing at itself. An unknown species is stored
    hyphenated.
    """
    cache = await _profiles()
    stored = _match(cache.by_id, requested)
    if stored is None:
        return canonical_species_id(requested)
    canonical = canonical_species_id(stored)
    return canonical if _match(cache.by_id, canonical) == stored else stored


# ── Writing profiles ──────────────────────────────────────────────────


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
    _invalidate()


async def _find_row(db, profile_id: str):
    """(stored id, is_builtin) of the profile `profile_id` names, the way
    _match finds it, on the caller's connection; None if none does."""
    for candidate in species_id_candidates(profile_id):
        cursor = await db.execute(
            "SELECT id, is_builtin FROM species_profiles WHERE id = ?", (candidate,)
        )
        row = await cursor.fetchone()
        if row:
            return row
    cursor = await db.execute(
        "SELECT id, is_builtin FROM species_profiles WHERE replace(id, '_', '-') = ? "
        "ORDER BY id LIMIT 1",
        (canonical_species_id(profile_id),),
    )
    return await cursor.fetchone()


def _check_setpoints(profile: SpeciesProfile) -> None:
    if problems := profile_problems(profile):
        raise InvalidProfileError(
            f"Species profile '{profile.id}' has setpoints automation cannot run: "
            + "; ".join(problems)
        )


async def create_profile(profile: SpeciesProfile) -> SpeciesProfile:
    """Store a custom profile. Raises InvalidProfileError for setpoints
    automation cannot run and ProfileExistsError for an id a stored profile
    already answers to (in either separator spelling)."""
    _check_setpoints(profile)
    async with get_db() as db:
        row = await _find_row(db, profile.id)
        if row is not None:
            raise ProfileExistsError(profile.id, row["id"])
        try:
            await db.execute(
                "INSERT INTO species_profiles (id, data, is_builtin) VALUES (?, ?, 0)",
                (profile.id, profile.model_dump_json()),
            )
        except sqlite3.IntegrityError:  # created by a concurrent request
            raise ProfileExistsError(profile.id, profile.id) from None
        await db.commit()
    _invalidate()
    return profile


async def update_profile(profile_id: str, profile: SpeciesProfile) -> SpeciesProfile | None:
    """Replace a custom profile. None if unknown; raises BuiltinProfileReadOnly
    for a built-in, and InvalidProfileError for setpoints automation cannot
    run or a body whose id names another profile (it was stored under this
    one's row, listed under an id nothing could reach)."""
    async with get_db() as db:
        row = await _find_row(db, profile_id)
        if not row:
            return None
        if row["is_builtin"]:
            raise BuiltinProfileReadOnly(row["id"])
        if canonical_species_id(profile.id) != canonical_species_id(row["id"]):
            raise InvalidProfileError(
                f"The body's id '{profile.id}' is not the profile being updated "
                f"('{row['id']}'): to store it under a new id, POST /api/species"
            )
        _check_setpoints(profile)
        # Stored under the row's own spelling of the id.
        profile = profile.model_copy(update={"id": row["id"]})
        await db.execute(
            "UPDATE species_profiles SET data = ?, updated_at = unixepoch('now') WHERE id = ?",
            (profile.model_dump_json(), row["id"]),
        )
        await db.commit()
    _invalidate()
    return profile


async def delete_profile(profile_id: str) -> bool:
    """Delete a custom profile. False for an unknown id or a built-in; raises
    ProfileInUseError while an active grow runs on it (its sessions resolve
    their species id to it, however the id is spelled)."""
    async with get_db() as db:
        row = await _find_row(db, profile_id)
        if not row or row["is_builtin"]:
            return False
        cursor = await db.execute("SELECT id FROM species_profiles")
        stored = {r["id"] for r in await cursor.fetchall()}
        cursor = await db.execute(
            "SELECT id, name, species_profile_id FROM sessions WHERE status = 'active' ORDER BY id"
        )
        users = [(r["id"], r["name"]) for r in await cursor.fetchall()
                 if _match(stored, r["species_profile_id"] or "") == row["id"]]
        if users:
            raise ProfileInUseError(row["id"], users)
        await db.execute("DELETE FROM species_profiles WHERE id = ?", (row["id"],))
        await db.commit()
    _invalidate()
    return True
