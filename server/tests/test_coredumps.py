"""Coredump reassembly — storage location, cross-upload chunk mixing, and the
store-then-ack protocol (firmware/lib/sp_core/coredump_drain.h is the node
half): the Pi acknowledges a dump only once it is durably on disk, only when
the bytes hash to the node's id, and exactly once per stored copy — a
re-upload is re-acknowledged without a second file or alert."""

import base64
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app import mqtt as mqtt_mod
from app.config import settings
from app.hardware import coredumps
from app.mqtt import _handle_message, mqtt_publish

NODE_TOPIC = "sporeprint/{node}/coredump/chunk"
DRAIN_H = Path(__file__).resolve().parents[2] / "firmware" / "lib" / "sp_core" / "coredump_drain.h"


def _chunk(seq, total, data: bytes, dump_id: str | None = None):
    c = {"seq": seq, "total": total, "size": len(data),
         "b64_data": base64.b64encode(data).decode()}
    if dump_id is not None:
        c["coredump_id"] = dump_id
    return c


def _chunks(blob: bytes, size: int = 512, *, dump_id: str | None = None):
    """The node's chunking: 512 raw bytes per chunk, every chunk tagged with
    the SHA-256 of the whole dump (unless dump_id is given explicitly)."""
    if dump_id is None:
        dump_id = hashlib.sha256(blob).hexdigest()
    parts = [blob[i:i + size] for i in range(0, len(blob), size)]
    return [_chunk(i, len(parts), p, dump_id) for i, p in enumerate(parts)]


@pytest.fixture(autouse=True)
def _clear_assemblies():
    coredumps._assemblies.clear()
    yield
    coredumps._assemblies.clear()


@pytest.fixture()
def dumps_dir(tmp_path, monkeypatch):
    d = tmp_path / "dumps"
    monkeypatch.setattr(coredumps, "COREDUMP_DIR", d)
    return d


@pytest.fixture()
def quiet_cloud(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.mqtt.forward_event", _noop)


# ── storage ─────────────────────────────────────────────────────

async def test_dumps_are_stored_next_to_the_database(tmp_path, monkeypatch):
    """The default directory follows settings.database_path (the persistent,
    appuser-owned /data/db volume in Docker), not a CWD-relative path under
    the read-only /app image directory."""
    db_dir = tmp_path / "db"
    monkeypatch.setattr(settings, "database_path", str(db_dir / "sporeprint.db"))
    monkeypatch.chdir(tmp_path)

    stored = await coredumps.ingest_chunk("node-x1", _chunk(0, 1, b"ELF-ONE-CHUNK"))

    assert stored is not None
    out = stored.path
    assert out.parent == db_dir / "coredumps"
    assert out.read_bytes() == b"ELF-ONE-CHUNK"
    assert not (tmp_path / "data").exists()  # nothing written relative to CWD
    listed = coredumps.list_dumps()
    assert [d["filename"] for d in listed] == [out.name]
    assert coredumps.dump_path(out.name) == out


async def test_unwritable_dump_dir_is_logged_not_raised(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setattr(coredumps, "COREDUMP_DIR", blocker / "dumps")

    with caplog.at_level(logging.ERROR, logger=coredumps.__name__):
        out = await coredumps.ingest_chunk("node-x2", _chunk(0, 1, b"ELF"))

    assert out is None
    assert "node-x2" not in coredumps._assemblies
    assert any("could not be written" in r.getMessage() for r in caplog.records)


async def test_chunks_from_a_new_upload_never_merge_into_an_old_assembly(dumps_dir):
    """seq 0 of a retry upload is lost (QoS0): its later chunks carry a
    different `total` and must be dropped, not spliced into the old dump."""
    assert await coredumps.ingest_chunk("node-x3", _chunk(0, 3, b"OLD0")) is None
    for seq in (1, 2, 3):
        assert await coredumps.ingest_chunk("node-x3", _chunk(seq, 4, b"NEW%d" % seq)) is None

    assert not dumps_dir.exists()
    asm = coredumps._assemblies["node-x3"]
    assert asm.total == 3
    assert asm.chunks == {0: b"OLD0"}


async def test_chunks_of_another_dump_id_never_merge(dumps_dir):
    """Same chunk count, different dump (the node panicked again mid-retry):
    the id keeps the two apart."""
    a = _chunks(b"A" * 1024)
    b = _chunks(b"B" * 1024)
    assert await coredumps.ingest_chunk("node-x3b", a[0]) is None
    assert await coredumps.ingest_chunk("node-x3b", b[1]) is None  # orphan
    assert coredumps._assemblies["node-x3b"].chunks.keys() == {0}
    stored = await coredumps.ingest_chunk("node-x3b", a[1])
    assert stored is not None and stored.path.read_bytes() == b"A" * 1024


async def test_new_total_chunk_beyond_old_total_does_not_crash(dumps_dir):
    """A new-upload chunk whose seq >= the old assembly's total previously got
    stored and later crashed completion with KeyError."""
    await coredumps.ingest_chunk("node-x4", _chunk(0, 3, b"A"))
    await coredumps.ingest_chunk("node-x4", _chunk(3, 5, b"stray"))
    await coredumps.ingest_chunk("node-x4", _chunk(4, 5, b"stray"))
    # The old upload still completes cleanly with only its own chunks.
    await coredumps.ingest_chunk("node-x4", _chunk(2, 3, b"C"))
    out = await coredumps.ingest_chunk("node-x4", _chunk(1, 3, b"B"))

    assert out is not None
    assert out.path.read_bytes() == b"ABC"


async def test_seq0_with_new_total_restarts_the_assembly(dumps_dir):
    await coredumps.ingest_chunk("node-x5", _chunk(0, 3, b"OLD"))
    await coredumps.ingest_chunk("node-x5", _chunk(0, 2, b"NE"))
    out = await coredumps.ingest_chunk("node-x5", _chunk(1, 2, b"W!"))

    assert out is not None
    assert out.path.read_bytes() == b"NEW!"


async def test_write_is_atomic_and_leaves_no_temp_file(dumps_dir, monkeypatch):
    synced = []
    real_fsync = os.fsync
    monkeypatch.setattr(coredumps.os, "fsync",
                        lambda fd: (synced.append(fd), real_fsync(fd))[1])
    stored = await coredumps.ingest_chunk("node-x6", _chunk(0, 1, b"ELF!"))
    assert stored is not None
    assert synced, "the dump was never fsynced before being reported stored"
    assert [p.name for p in dumps_dir.iterdir()] == [stored.path.name]


async def test_a_failed_write_leaves_neither_file_nor_temp(dumps_dir, monkeypatch):
    def _boom(fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(coredumps.os, "fsync", _boom)
    blob = b"X" * 600
    for c in _chunks(blob):
        stored = await coredumps.ingest_chunk("node-x7", c)
    assert stored is None
    assert list(dumps_dir.iterdir()) == []


async def test_partial_writes_are_discarded_and_never_served(dumps_dir):
    dumps_dir.mkdir()
    (dumps_dir / "node-x8-20261005T000000Z.elf.part").write_bytes(b"half")
    (dumps_dir / "node-x8-20261005T000001Z.elf").write_bytes(b"whole")
    assert coredumps.dump_path("node-x8-20261005T000000Z.elf.part") is None
    assert [d["filename"] for d in coredumps.list_dumps()] == [
        "node-x8-20261005T000001Z.elf"]
    assert coredumps.discard_partial_writes() == 1
    assert sorted(p.name for p in dumps_dir.iterdir()) == [
        "node-x8-20261005T000001Z.elf"]


# ── store-then-ack ──────────────────────────────────────────────

async def test_dump_is_acked_only_after_it_is_durably_stored(dumps_dir, monkeypatch, quiet_cloud):
    """The ack lets the node erase its only copy — so at the moment it is
    published, the complete file must already be in place (renamed from its
    fsynced temp file), and the ack names the node's id."""
    blob = bytes(range(256)) * 5  # 1280 B → 3 chunks
    dump_id = hashlib.sha256(blob).hexdigest()
    seen = []

    async def _publish(topic, payload):
        files = list(dumps_dir.glob("*.elf")) if dumps_dir.exists() else []
        seen.append((topic, payload, [(f.name, f.read_bytes()) for f in files],
                     list(dumps_dir.glob("*.part")) if dumps_dir.exists() else []))
        return True

    monkeypatch.setattr(mqtt_mod, "mqtt_publish", _publish)
    sio = AsyncMock()
    for c in _chunks(blob):
        await _handle_message(sio, NODE_TOPIC.format(node="node-k1"), c)

    assert len(seen) == 1
    topic, payload, files, partials = seen[0]
    assert topic == "sporeprint/node-k1/cmd/coredump_ack"
    assert payload == {"coredump_id": dump_id}
    assert len(files) == 1 and files[0][1] == blob
    assert files[0][0].endswith(f"-{dump_id[:16]}.elf")
    assert partials == []
    # …and the alert went out too, once.
    assert sio.emit.await_args.args[0] == "alert"
    assert sio.emit.await_args.args[1]["filename"] == files[0][0]


async def test_no_ack_until_the_last_chunk(dumps_dir, mock_mqtt, quiet_cloud):
    blob = b"Z" * 2000
    sio = AsyncMock()
    chunks = _chunks(blob)
    for c in chunks[:-1]:
        await _handle_message(sio, NODE_TOPIC.format(node="node-k2"), c)
    assert mock_mqtt == []
    assert not dumps_dir.exists()
    await _handle_message(sio, NODE_TOPIC.format(node="node-k2"), chunks[-1])
    assert [t for t, _ in mock_mqtt] == ["sporeprint/node-k2/cmd/coredump_ack"]


async def test_no_ack_when_the_store_fails(tmp_path, monkeypatch, mock_mqtt, quiet_cloud):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setattr(coredumps, "COREDUMP_DIR", blocker / "dumps")
    sio = AsyncMock()
    for c in _chunks(b"ELF" * 100):
        await _handle_message(sio, NODE_TOPIC.format(node="node-k3"), c)
    assert mock_mqtt == []  # the node keeps its copy and uploads again
    sio.emit.assert_not_awaited()


async def test_no_store_and_no_ack_when_bytes_do_not_match_the_id(dumps_dir, mock_mqtt, quiet_cloud, caplog):
    blob = b"Q" * 1500
    wrong = hashlib.sha256(b"something else").hexdigest()
    sio = AsyncMock()
    with caplog.at_level(logging.ERROR, logger=coredumps.__name__):
        for c in _chunks(blob, dump_id=wrong):
            await _handle_message(sio, NODE_TOPIC.format(node="node-k4"), c)
    assert mock_mqtt == []
    assert not dumps_dir.exists()
    sio.emit.assert_not_awaited()
    assert any("does not match its id" in r.getMessage() for r in caplog.records)


async def test_reupload_is_reacked_without_a_second_copy_or_alert(dumps_dir, mock_mqtt, quiet_cloud):
    """The first ack was lost, so the node uploads the same dump again: the Pi
    must acknowledge it again (or the node never erases) — idempotently."""
    blob = os.urandom(3000)
    dump_id = hashlib.sha256(blob).hexdigest()
    sio = AsyncMock()
    for _ in range(3):
        for c in _chunks(blob):
            await _handle_message(sio, NODE_TOPIC.format(node="node-k5"), c)

    assert mock_mqtt == [("sporeprint/node-k5/cmd/coredump_ack",
                          {"coredump_id": dump_id})] * 3
    files = list(dumps_dir.glob("*.elf"))
    assert len(files) == 1 and files[0].read_bytes() == blob
    assert sio.emit.await_count == 1  # one panic, one alert


async def test_same_dump_from_another_node_is_its_own_file(dumps_dir, mock_mqtt, quiet_cloud):
    blob = b"same" * 200
    sio = AsyncMock()
    for node in ("node-k6", "node-k7"):
        for c in _chunks(blob):
            await _handle_message(sio, NODE_TOPIC.format(node=node), c)
    assert len(list(dumps_dir.glob("node-k6-*.elf"))) == 1
    assert len(list(dumps_dir.glob("node-k7-*.elf"))) == 1
    assert [t for t, _ in mock_mqtt] == [
        "sporeprint/node-k6/cmd/coredump_ack", "sporeprint/node-k7/cmd/coredump_ack"]


async def test_a_new_panic_after_an_acked_one_is_stored_and_acked(dumps_dir, mock_mqtt, quiet_cloud):
    sio = AsyncMock()
    for blob in (b"first-panic" * 80, b"second-panic" * 80):
        for c in _chunks(blob):
            await _handle_message(sio, NODE_TOPIC.format(node="node-k8"), c)
    assert len(list(dumps_dir.glob("node-k8-*.elf"))) == 2
    assert len(mock_mqtt) == 2
    assert sio.emit.await_count == 2


async def test_firmware_without_ids_is_stored_but_never_acked(dumps_dir, mock_mqtt, quiet_cloud):
    """Older firmware erases its dump as soon as the last chunk is out and
    never listens for an ack: unchanged behaviour, no cmd frame."""
    blob = b"legacy" * 100
    parts = [blob[i:i + 512] for i in range(0, len(blob), 512)]
    sio = AsyncMock()
    for i, p in enumerate(parts):
        await _handle_message(sio, NODE_TOPIC.format(node="node-k9"),
                              _chunk(i, len(parts), p))
    files = list(dumps_dir.glob("node-k9-*.elf"))
    assert len(files) == 1 and files[0].read_bytes() == blob
    assert mock_mqtt == []
    assert sio.emit.await_count == 1


async def test_malformed_id_stores_without_ack(dumps_dir, mock_mqtt, quiet_cloud):
    sio = AsyncMock()
    await _handle_message(sio, NODE_TOPIC.format(node="node-k10"),
                          _chunk(0, 1, b"ELF", dump_id="ABC123"))
    assert len(list(dumps_dir.glob("node-k10-*.elf"))) == 1
    assert mock_mqtt == []


async def test_failed_ack_publish_is_logged(dumps_dir, mock_mqtt, quiet_cloud, caplog):
    mock_mqtt.mock.return_value = False
    sio = AsyncMock()
    with caplog.at_level(logging.WARNING, logger=mqtt_mod.__name__):
        for c in _chunks(b"E" * 700):
            await _handle_message(sio, NODE_TOPIC.format(node="node-k11"), c)
    assert len(mock_mqtt) == 1
    assert any("coredump ack to node-k11 not sent" in r.getMessage()
               for r in caplog.records)


async def test_ack_is_a_signed_topic_bound_cmd_frame(monkeypatch):
    """The ack rides the normal cmd/* path: HMAC-signed with topic + nonce,
    and well under the node's 1024-byte inbound cap."""
    published = []

    class _Client:
        async def publish(self, topic, payload):
            published.append((topic, payload))

    monkeypatch.setattr(mqtt_mod, "_client", _Client())
    monkeypatch.setattr(settings, "mqtt_hmac_key", "k" * 32)
    dump_id = hashlib.sha256(b"x").hexdigest()
    topic = f"sporeprint/node-k12/cmd/{coredumps.ACK_SUFFIX}"
    assert await mqtt_publish(topic, {"coredump_id": dump_id})
    (t, raw), = published
    frame = json.loads(raw)
    assert t == topic
    assert frame["coredump_id"] == dump_id
    assert frame["topic"] == topic and frame["nonce"] and frame["signature"]
    assert len(raw.encode()) < mqtt_mod._NODE_INBOUND_FRAME_CAP


# ── the firmware's half of the contract ────────────────────────

def test_firmware_chunk_and_ack_contract_match_the_pi():
    """sp_core/coredump_drain.h builds the chunk the Pi parses and names the
    cmd suffix the Pi acknowledges on — a rename on either side fails here."""
    src = DRAIN_H.read_text()
    m = re.search(r'kCoredumpAckSuffix\s*=\s*"([^"]+)"', src)
    assert m and m.group(1) == coredumps.ACK_SUFFIX
    body = src[src.index("inline void build_coredump_chunk("):]
    body = body[:body.index("\n}\n")]
    assert set(re.findall(r'doc\["([^"]+)"\]', body)) == {
        "seq", "total", "size", "b64_data", "coredump_id"}
    m = re.search(r"kCoredumpChunkBytes\s*=\s*(\d+)", src)
    assert m and int(m.group(1)) * 256 <= coredumps.MAX_DUMP_BYTES
