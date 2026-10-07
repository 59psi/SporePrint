"""Firmware coredump reassembly and store-then-ack.

ESP32 nodes drain panic dumps as base64 chunks on
``sporeprint/<id>/coredump/chunk`` ({seq, total, size, b64_data,
coredump_id}). This module reassembles them in memory and writes the
completed ELF to ``<database dir>/coredumps/`` (``/data/db/coredumps`` in
Docker — the persistent, appuser-owned volume) for offline decoding with
espcoredump.py (decoding needs the matching firmware ELF — we store, not
parse).

Store-then-ack (firmware/lib/sp_core/coredump_drain.h is the node half):

* ``coredump_id`` is the lowercase hex SHA-256 of the whole dump. The
  reassembled bytes must hash to it, or nothing is stored and nothing is
  acknowledged (the node keeps its copy and uploads again).
* The file is written durably — a temporary file, fsync, atomic rename,
  directory fsync — and only then does ``ingest_chunk`` return; the caller
  (``app/mqtt.py``) then publishes the signed ``cmd/coredump_ack``
  ``{"coredump_id"}``. The node erases its flash copy only on that ack, so
  a Pi crash, full disk or lost chunk can no longer destroy the only copy.
* Idempotent: a re-upload of a dump already stored (its ack was lost)
  writes nothing, raises no second alert, and is acknowledged again. The
  file name carries the id's first 16 hex digits
  (``<node>-<utc_ts>-<id16>.elf``), which is what the lookup matches.
* Firmware that sends no ``coredump_id`` (it erases its dump as soon as the
  last chunk is out) is stored as before, as ``<node>-<utc_ts>.elf``, and is
  never acknowledged.

In-flight assemblies are abandoned after 10 minutes; the node keeps the
flash dump until it is acknowledged, so an abandoned upload is retried.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings

log = logging.getLogger(__name__)

# Explicit override (tests). None = derive from settings.database_path at call
# time, so dumps land on the same persistent volume as the SQLite DB. A
# CWD-relative default resolved to /app/data/coredumps in the image, which the
# non-root appuser cannot create and which a rebuild would wipe anyway.
COREDUMP_DIR: Path | None = None
ASSEMBLY_TIMEOUT_S = 600
MAX_DUMP_BYTES = 256 * 1024  # 4x the largest partition we ship — sanity cap

# The Pi → node acknowledgement: sporeprint/<node>/cmd/<ACK_SUFFIX>
# {"coredump_id": "<id>"} (sp_core/coredump_drain.h kCoredumpAckSuffix).
ACK_SUFFIX = "coredump_ack"
_COREDUMP_ID_RE = re.compile(r"[0-9a-f]{64}")
_ID_IN_NAME = 16  # hex digits of the id in the file name
_PARTIAL_SUFFIX = ".part"


@dataclass(frozen=True)
class StoredCoredump:
    """A completed upload, durably on disk."""

    path: Path
    # The node's id to acknowledge; None for firmware that sends none.
    coredump_id: str | None
    # False when this exact dump was stored before (a re-upload after a lost
    # ack): nothing was written and no new alert is due.
    new: bool


@dataclass
class _Assembly:
    total: int
    dump_id: str | None = None
    chunks: dict = field(default_factory=dict)  # seq -> bytes
    started_at: float = field(default_factory=time.time)

    def size_bytes(self) -> int:
        return sum(len(c) for c in self.chunks.values())


_assemblies: dict[str, _Assembly] = {}


def coredump_dir() -> Path:
    """Directory completed dumps are written to and served from."""
    if COREDUMP_DIR is not None:
        return Path(COREDUMP_DIR)
    return Path(settings.database_path).parent / "coredumps"


def _safe_node(node_id: str) -> str:
    return "".join(ch for ch in node_id if ch.isalnum() or ch in "-_")


def _reap_stale(now: float) -> None:
    stale = [nid for nid, a in _assemblies.items()
             if now - a.started_at > ASSEMBLY_TIMEOUT_S]
    for nid in stale:
        log.warning("coredump assembly for %s abandoned (%d/%d chunks)",
                    nid, len(_assemblies[nid].chunks), _assemblies[nid].total)
        del _assemblies[nid]


def _chunk_dump_id(node_id: str, payload: dict, seq: int) -> str | None:
    raw = payload.get("coredump_id")
    if raw is None:
        return None
    if isinstance(raw, str) and _COREDUMP_ID_RE.fullmatch(raw):
        return raw
    if seq == 0:
        log.warning("coredump from %s carries a malformed coredump_id — "
                    "stored without an acknowledgement", node_id)
    return None


def _assemble(node_id: str, payload: dict, now: float) -> tuple[bytes, str | None] | None:
    """Feed one chunk; returns (dump bytes, node's id) when a dump completes."""
    _reap_stale(now)

    try:
        seq = int(payload["seq"])
        total = int(payload["total"])
        data = base64.b64decode(payload["b64_data"], validate=True)
    except (KeyError, TypeError, ValueError, binascii.Error) as e:
        log.warning("coredump chunk from %s rejected: %s", node_id, e)
        return None
    if total <= 0 or seq < 0 or seq >= total:
        log.warning("coredump chunk from %s rejected: seq %d/total %d",
                    node_id, seq, total)
        return None
    dump_id = _chunk_dump_id(node_id, payload, seq)

    asm = _assemblies.get(node_id)
    if (asm is None or asm.total != total or asm.dump_id != dump_id
            or seq in asm.chunks):
        # New upload (or a node restarted its upload) — begin fresh on seq 0,
        # otherwise drop the orphan chunk.
        if seq == 0:
            asm = _Assembly(total=total, dump_id=dump_id)
            _assemblies[node_id] = asm
        elif asm is None:
            log.warning("coredump chunk from %s out of order (seq %d, no "
                        "assembly)", node_id, seq)
            return None
        elif asm.total != total or asm.dump_id != dump_id:
            # A different upload whose seq 0 we never saw (QoS0 loss). Never
            # splice it into the in-flight assembly — that writes an ELF mixing
            # two dumps, or KeyErrors on a seq beyond the old total.
            log.warning("coredump chunk from %s dropped (seq %d/total %d does "
                        "not match the in-flight upload of %d chunks)",
                        node_id, seq, total, asm.total)
            return None

    if asm.size_bytes() + len(data) > MAX_DUMP_BYTES:
        log.warning("coredump from %s exceeds %d bytes — dropped",
                    node_id, MAX_DUMP_BYTES)
        del _assemblies[node_id]
        return None

    asm.chunks[seq] = data
    if len(asm.chunks) < asm.total:
        return None

    del _assemblies[node_id]
    return b"".join(asm.chunks[i] for i in range(asm.total)), asm.dump_id


def find_stored(node_id: str, dump_id: str) -> Path | None:
    """The stored file of this node's dump `dump_id`, if there is one."""
    if not _COREDUMP_ID_RE.fullmatch(dump_id):
        return None
    base = coredump_dir()
    if not base.is_dir():
        return None
    pattern = f"{_safe_node(node_id)}-*-{dump_id[:_ID_IN_NAME]}.elf"
    return next(iter(sorted(base.glob(pattern))), None)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return  # not supported here (non-POSIX): the rename is still atomic
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_durably(out: Path, data: bytes) -> None:
    """Write `out` so it is complete on disk when this returns, or absent."""
    tmp = out.with_name(out.name + _PARTIAL_SUFFIX)
    try:
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, out)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(out.parent)


def store_dump(node_id: str, data: bytes, dump_id: str | None,
               now: float) -> StoredCoredump | None:
    """Durably store one reassembled dump (blocking file I/O)."""
    if dump_id is not None:
        existing = find_stored(node_id, dump_id)
        if existing is not None:
            log.info("coredump %s from %s already stored as %s — "
                     "acknowledging again", dump_id[:_ID_IN_NAME], node_id,
                     existing.name)
            return StoredCoredump(existing, dump_id, new=False)

    out_dir = coredump_dir()
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    name = f"{_safe_node(node_id)}-{ts}"
    if dump_id is not None:
        name += f"-{dump_id[:_ID_IN_NAME]}"
    out = out_dir / f"{name}.elf"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_durably(out, data)
    except OSError as e:
        log.error("coredump from %s could not be written to %s: %s — %s; "
                  "make the directory writable by the server user",
                  node_id, out_dir, e,
                  "the node keeps its copy and uploads it again"
                  if dump_id is not None else "the dump is lost")
        return None
    log.warning("coredump from %s written to %s (%d bytes) — node panicked "
                "on an earlier run; decode with espcoredump.py + the matching "
                "ELF", node_id, out, len(data))
    return StoredCoredump(out, dump_id, new=True)


async def ingest_chunk(node_id: str, payload: dict) -> StoredCoredump | None:
    """Feed one chunk. Returns the stored dump once one completes — durably
    on disk, so the caller may acknowledge ``coredump_id`` right away."""
    now = time.time()
    assembled = _assemble(node_id, payload, now)
    if assembled is None:
        return None
    data, dump_id = assembled
    if dump_id is not None:
        digest = hashlib.sha256(data).hexdigest()
        if digest != dump_id:
            log.error("coredump from %s does not match its id (%s… announced, "
                      "%s… received, %d bytes) — not stored, not acknowledged; "
                      "the node keeps its copy and uploads it again",
                      node_id, dump_id[:_ID_IN_NAME], digest[:_ID_IN_NAME],
                      len(data))
            return None
    # fsync on an SD card can take a while — keep it off the event loop.
    return await asyncio.to_thread(store_dump, node_id, data, dump_id, now)


def discard_partial_writes() -> int:
    """Delete temp files a crash mid-write left behind (boot housekeeping).

    Their uploads were never acknowledged, so the node still holds those dumps.
    """
    base = coredump_dir()
    if not base.is_dir():
        return 0
    removed = 0
    for p in base.glob(f"*{_PARTIAL_SUFFIX}"):
        try:
            p.unlink()
            removed += 1
        except OSError as e:
            log.warning("could not remove partial coredump %s: %s", p, e)
    return removed


def list_dumps() -> list[dict]:
    base = coredump_dir()
    if not base.exists():
        return []
    out = []
    for p in sorted(base.glob("*.elf"), reverse=True):
        out.append({
            "filename": p.name,
            "size_bytes": p.stat().st_size,
            "modified_at": p.stat().st_mtime,
        })
    return out


def dump_path(filename: str) -> Path | None:
    """Resolve a dump filename safely inside the coredump directory."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    if not filename.endswith(".elf"):
        return None  # never a half-written .part
    p = coredump_dir() / filename
    return p if p.is_file() else None
