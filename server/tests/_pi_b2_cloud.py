"""Shared builders for the cloud relay tests: signed frames, a recording
Socket.IO stand-in, and hardware-node rows."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from app.db import get_db


def sign(frame: dict, key: str) -> dict:
    """Sign `frame` as the cloud relay does: HMAC-SHA256 with the device token
    over the canonical JSON of every field but `signature`. Written out here
    rather than borrowed from app.cloud.signing, so a drift in the Pi's
    canonical form fails the tests instead of following them."""
    filtered = {k: v for k, v in frame.items() if k != "signature"}
    body = json.dumps(filtered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {**frame, "signature": digest}


class FakeSio:
    """Records what a handler emits on the cloud socket."""

    def __init__(self) -> None:
        self.emits: list[tuple[str, dict]] = []

    async def emit(self, event: str, data: dict) -> None:
        self.emits.append((event, data))

    def last(self, event: str) -> dict:
        assert self.emits, "the handler emitted nothing"
        name, data = self.emits[-1]
        assert name == event, (name, data)
        return data


async def register_node(node_id: str, node_type: str, *, channels: list[str] | None = None,
                        roles: list[str] | None = None,
                        last_seen: float | None = None) -> None:
    """A hardware_nodes row. `channels` None is a node that has not reported
    its channels yet."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, roles, channels, last_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (node_id, node_type,
             json.dumps(roles) if roles is not None else None,
             json.dumps(channels) if channels is not None else None,
             time.time() if last_seen is None else last_seen),
        )
        await db.commit()
