"""Vision frame retention (srv-rest#9).

Nothing ever deleted a vision frame: ~96 UXGA JPEGs/day per camera accumulated
forever on the SD card that also holds the SQLite DB. Frames older than the
full-retention window are now thinned to one per node per day, keeping every
frame that matters (non-healthy Claude read, active-learning label, or one
referenced by a contamination event / note / harvest).
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import app.vision.router as vrouter
from app.config import settings
from app.db import get_db
from app.vision import service
from app.vision.service import (
    VISION_FULL_RETENTION_DAYS,
    insert_frame,
    maybe_schedule_vision_prune,
    prune_vision_frames,
)

DAY = 86400
NOW = 1_790_000_000.0 - (1_790_000_000.0 % DAY) + 15 * 3600  # 15:00 UTC


@pytest.fixture(autouse=True)
def _reset_prune_state():
    service._last_vision_prune = 0.0
    service._vision_prune_tasks.clear()
    yield
    service._last_vision_prune = 0.0
    service._vision_prune_tasks.clear()


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    d = tmp_path / "frames"
    d.mkdir()
    monkeypatch.setattr(settings, "vision_storage", str(d))
    return d


async def _frame(directory, name, ts, analysis_local=None, analysis_claude=None,
                 session_id=None, created_at=None) -> tuple[int, object]:
    """Insert a frame + file. `created_at` (arrival time) defaults to `ts`, i.e.
    a synced camera whose frame arrived when it was captured."""
    p = directory / name
    p.write_bytes(b"\xff\xd8\xff\xe0" + name.encode())
    fid = await insert_frame(session_id=session_id, node_id="cam-01", timestamp=ts,
                             file_path=str(p.resolve()), resolution="", flash_used=1)
    async with get_db() as db:
        await db.execute(
            "UPDATE vision_frames SET analysis_local = ?, analysis_claude = ?, created_at = ? "
            "WHERE id = ?",
            (json.dumps(analysis_local) if analysis_local else None,
             json.dumps(analysis_claude) if analysis_claude else None,
             ts if created_at is None else created_at, fid),
        )
        await db.commit()
    return fid, p


async def _ids() -> set[int]:
    async with get_db() as db:
        rows = await (await db.execute("SELECT id FROM vision_frames")).fetchall()
    return {r["id"] for r in rows}


@pytest.mark.parametrize("batch", [500, 2])
async def test_old_frames_are_thinned_but_notable_frames_survive(storage, tmp_path, monkeypatch,
                                                                 batch):
    # batch=2 forces the multi-batch path the first pass over a large backlog takes.
    monkeypatch.setattr(service, "_VISION_PRUNE_BATCH", batch)
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO sessions (name, species_profile_id, status) VALUES ('s', 'blue-oyster', 'completed')"
        )
        sid = cur.lastrowid
        await db.commit()

    old = NOW - (VISION_FULL_RETENTION_DAYS + 10) * DAY
    old_day = old - (old % DAY)
    other_day = old_day - DAY

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outside_id, outside_path = await _frame(elsewhere, "outside.jpg", old_day + 1 * 3600)
    plain_id, plain_path = await _frame(storage, "plain.jpg", old_day + 2 * 3600)
    contam_id, _ = await _frame(storage, "contam.jpg", old_day + 7 * 3600,
                                analysis_claude={"health_assessment": "contaminated"})
    labelled_id, _ = await _frame(storage, "labelled.jpg", old_day + 13 * 3600,
                                  analysis_local={"prediction": "healthy", "user_label": "trich_early",
                                                  "user_confirmed": False})
    keeper_id, _ = await _frame(storage, "keeper.jpg", old_day + 19 * 3600,
                                analysis_claude={"health_assessment": "healthy"})

    ref_event_id, _ = await _frame(storage, "ref_event.jpg", other_day + 1 * 3600, session_id=sid)
    ref_note_id, _ = await _frame(storage, "ref_note.jpg", other_day + 2 * 3600, session_id=sid)
    ref_harvest_id, _ = await _frame(storage, "ref_harvest.jpg", other_day + 3 * 3600, session_id=sid)
    other_plain_id, other_plain_path = await _frame(storage, "other_plain.jpg", other_day + 4 * 3600)
    other_keeper_id, _ = await _frame(storage, "other_keeper.jpg", other_day + 20 * 3600)

    recent_ids = {
        (await _frame(storage, f"recent{i}.jpg", NOW - 5 * DAY + i * 900))[0] for i in range(3)
    }

    async with get_db() as db:
        await db.execute(
            "INSERT INTO contamination_events (session_id, source, frame_id) VALUES (?, 'manual', ?)",
            (sid, ref_event_id),
        )
        await db.execute(
            "INSERT INTO session_notes (session_id, text, image_id) VALUES (?, 'look', ?)",
            (sid, ref_note_id),
        )
        await db.execute(
            "INSERT INTO harvests (session_id, flush_number, image_ids) VALUES (?, 1, ?)",
            (sid, json.dumps([ref_harvest_id])),
        )
        await db.commit()

    freed_expected = plain_path.stat().st_size + other_plain_path.stat().st_size
    result = await prune_vision_frames(now=NOW)

    remaining = await _ids()
    assert remaining == {
        outside_id, contam_id, labelled_id, keeper_id,
        ref_event_id, ref_note_id, ref_harvest_id, other_keeper_id,
    } | recent_ids
    assert result["frames_deleted"] == 2
    assert result["bytes_freed"] == freed_expected
    assert result["frames_kept_outside_storage"] == 1
    assert not plain_path.exists()
    assert not other_plain_path.exists()
    # A row whose file lives outside the storage dir (storage moved, tampered
    # file_path) is kept along with its file: deleting only the row would
    # orphan an image that no later pass could ever find again.
    assert outside_id in remaining
    assert outside_path.exists()

    # Idempotent: a second pass deletes nothing more.
    again = await prune_vision_frames(now=NOW)
    assert again["frames_deleted"] == 0
    assert await _ids() == remaining


async def test_prune_is_throttled(storage):
    t1 = await maybe_schedule_vision_prune()
    assert t1 is not None
    await t1
    assert await maybe_schedule_vision_prune() is None


def test_ingest_endpoint_schedules_retention(client, monkeypatch, storage):
    recorder = AsyncMock(return_value=None)
    monkeypatch.setattr(vrouter, "maybe_schedule_vision_prune", recorder)
    r = client.post(
        "/api/vision/frame",
        content=b"\xff\xd8\xff\xe0body",
        headers={"Content-Type": "image/jpeg", "X-Node-Id": "cam-01"},
    )
    assert r.status_code == 200, r.text
    recorder.assert_awaited_once()


async def test_legacy_uptime_timestamps_are_aged_by_arrival_time(storage):
    """Before srv-rest#7, an unsynced cam's uptime X-Timestamp (e.g. 900) was
    stored verbatim. Such a frame looks like 1970 by `timestamp`, so a prune
    keyed on it alone deleted frames ingested minutes ago. Age = arrival time
    (created_at) when that is later than the capture timestamp."""
    now = time.time()
    fresh = {
        (await _frame(storage, f"fresh{i}.jpg", 900.0 * (i + 1), created_at=now - 60))[0]
        for i in range(10)
    }
    # The same legacy stamps on frames that really did arrive 40 days ago are
    # thinned like any other expired day (one keeper per node per day).
    arrived = now - (VISION_FULL_RETENTION_DAYS + 10) * DAY
    arrived -= arrived % DAY
    stale = [
        (await _frame(storage, f"stale{i}.jpg", 900.0 * (i + 1), created_at=arrived + i * 900))[0]
        for i in range(4)
    ]

    result = await prune_vision_frames(now=now)

    remaining = await _ids()
    assert fresh <= remaining, "recently-arrived frames must never be pruned"
    assert remaining == fresh | {stale[-1]}
    assert result["frames_deleted"] == 3


async def test_file_deletion_runs_off_the_event_loop(storage, monkeypatch):
    """The first pass after an upgrade can unlink months of frames; doing that
    on the loop would stall MQTT ingest / automation / Socket.IO."""
    old = NOW - (VISION_FULL_RETENTION_DAYS + 5) * DAY
    old -= old % DAY
    for i in range(3):
        await _frame(storage, f"f{i}.jpg", old + i * 3600)

    on_loop: list[bool] = []
    real_unlink = Path.unlink

    def recording_unlink(self, *args, **kwargs):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", recording_unlink)
    result = await prune_vision_frames(now=NOW)
    assert result["frames_deleted"] == 2
    assert on_loop == [False, False]
