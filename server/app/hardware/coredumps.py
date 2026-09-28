"""Firmware coredump reassembly — v4.2.

ESP32 nodes drain panic dumps at boot as base64 chunks on
``sporeprint/<id>/coredump/chunk`` ({seq, total, size, b64_data}).
This module reassembles them in memory and writes the completed ELF to
``<database dir>/coredumps/<node_id>-<utc_ts>.elf`` (``/data/db/coredumps``
in Docker — the persistent, appuser-owned volume) for offline decoding with
espcoredump.py (decoding needs the matching firmware ELF — we store, not
parse).

In-flight assemblies are abandoned after 10 minutes; the firmware keeps
the flash partition intact until every chunk publishes, so an abandoned
upload retries on the node's next boot.
"""

from __future__ import annotations

import base64
import binascii
import logging
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


@dataclass
class _Assembly:
    total: int
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


def _reap_stale(now: float) -> None:
    stale = [nid for nid, a in _assemblies.items()
             if now - a.started_at > ASSEMBLY_TIMEOUT_S]
    for nid in stale:
        log.warning("coredump assembly for %s abandoned (%d/%d chunks)",
                    nid, len(_assemblies[nid].chunks), _assemblies[nid].total)
        del _assemblies[nid]


def ingest_chunk(node_id: str, payload: dict) -> Path | None:
    """Feed one chunk; returns the written file path when a dump completes."""
    now = time.time()
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

    asm = _assemblies.get(node_id)
    if asm is None or asm.total != total or seq in asm.chunks:
        # New upload (or a node rebooted mid-upload and restarted) — begin
        # fresh on seq 0, otherwise drop the orphan chunk.
        if seq == 0:
            asm = _Assembly(total=total)
            _assemblies[node_id] = asm
        elif asm is None:
            log.warning("coredump chunk from %s out of order (seq %d, no "
                        "assembly)", node_id, seq)
            return None
        elif asm.total != total:
            # A different upload whose seq 0 we never saw (QoS0 loss). Never
            # splice it into the in-flight assembly — that writes an ELF mixing
            # two dumps, or KeyErrors on a seq beyond the old total.
            log.warning("coredump chunk from %s dropped (seq %d/total %d does "
                        "not match in-flight upload of %d chunks)",
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

    # Complete — write in sequence order.
    del _assemblies[node_id]
    out_dir = coredump_dir()
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    safe_node = "".join(ch for ch in node_id if ch.isalnum() or ch in "-_")
    out = out_dir / f"{safe_node}-{ts}.elf"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        with out.open("wb") as f:
            for i in range(asm.total):
                f.write(asm.chunks[i])
    except OSError as e:
        log.error("coredump from %s could not be written to %s: %s — the dump "
                  "is lost; make the directory writable by the server user",
                  node_id, out_dir, e)
        return None
    log.warning("coredump from %s written to %s (%d bytes) — node panicked "
                "last boot; decode with espcoredump.py + the matching ELF",
                node_id, out, out.stat().st_size)
    return out


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
    p = coredump_dir() / filename
    return p if p.is_file() else None
