"""Coredump reassembly — storage location and cross-upload chunk mixing."""

import base64
import logging

import pytest

from app.config import settings
from app.hardware import coredumps


def _chunk(seq, total, data: bytes):
    return {"seq": seq, "total": total, "size": len(data),
            "b64_data": base64.b64encode(data).decode()}


@pytest.fixture(autouse=True)
def _clear_assemblies():
    coredumps._assemblies.clear()
    yield
    coredumps._assemblies.clear()


def test_dumps_are_stored_next_to_the_database(tmp_path, monkeypatch):
    """The default directory follows settings.database_path (the persistent,
    appuser-owned /data/db volume in Docker), not a CWD-relative path under
    the read-only /app image directory."""
    db_dir = tmp_path / "db"
    monkeypatch.setattr(settings, "database_path", str(db_dir / "sporeprint.db"))
    monkeypatch.chdir(tmp_path)

    out = coredumps.ingest_chunk("node-x1", _chunk(0, 1, b"ELF-ONE-CHUNK"))

    assert out is not None
    assert out.parent == db_dir / "coredumps"
    assert out.read_bytes() == b"ELF-ONE-CHUNK"
    assert not (tmp_path / "data").exists()  # nothing written relative to CWD
    listed = coredumps.list_dumps()
    assert [d["filename"] for d in listed] == [out.name]
    assert coredumps.dump_path(out.name) == out


def test_unwritable_dump_dir_is_logged_not_raised(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setattr(coredumps, "COREDUMP_DIR", blocker / "dumps")

    with caplog.at_level(logging.ERROR, logger=coredumps.__name__):
        out = coredumps.ingest_chunk("node-x2", _chunk(0, 1, b"ELF"))

    assert out is None
    assert "node-x2" not in coredumps._assemblies
    assert any("could not be written" in r.getMessage() for r in caplog.records)


def test_chunks_from_a_new_upload_never_merge_into_an_old_assembly(tmp_path, monkeypatch):
    """seq 0 of a retry upload is lost (QoS0): its later chunks carry a
    different `total` and must be dropped, not spliced into the old dump."""
    monkeypatch.setattr(coredumps, "COREDUMP_DIR", tmp_path / "dumps")

    assert coredumps.ingest_chunk("node-x3", _chunk(0, 3, b"OLD0")) is None
    for seq in (1, 2, 3):
        assert coredumps.ingest_chunk("node-x3", _chunk(seq, 4, b"NEW%d" % seq)) is None

    assert not (tmp_path / "dumps").exists()
    asm = coredumps._assemblies["node-x3"]
    assert asm.total == 3
    assert asm.chunks == {0: b"OLD0"}


def test_new_total_chunk_beyond_old_total_does_not_crash(tmp_path, monkeypatch):
    """A new-upload chunk whose seq >= the old assembly's total previously got
    stored and later crashed completion with KeyError."""
    monkeypatch.setattr(coredumps, "COREDUMP_DIR", tmp_path / "dumps")

    coredumps.ingest_chunk("node-x4", _chunk(0, 3, b"A"))
    coredumps.ingest_chunk("node-x4", _chunk(3, 5, b"stray"))
    coredumps.ingest_chunk("node-x4", _chunk(4, 5, b"stray"))
    # The old upload still completes cleanly with only its own chunks.
    coredumps.ingest_chunk("node-x4", _chunk(2, 3, b"C"))
    out = coredumps.ingest_chunk("node-x4", _chunk(1, 3, b"B"))

    assert out is not None
    assert out.read_bytes() == b"ABC"


def test_seq0_with_new_total_restarts_the_assembly(tmp_path, monkeypatch):
    monkeypatch.setattr(coredumps, "COREDUMP_DIR", tmp_path / "dumps")

    coredumps.ingest_chunk("node-x5", _chunk(0, 3, b"OLD"))
    coredumps.ingest_chunk("node-x5", _chunk(0, 2, b"NE"))
    out = coredumps.ingest_chunk("node-x5", _chunk(1, 2, b"W!"))

    assert out is not None
    assert out.read_bytes() == b"NEW!"
