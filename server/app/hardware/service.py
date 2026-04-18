"""Hardware node service layer — DB access + MQTT command dispatch.

Extracted from `hardware/router.py` in v3.3.2 (P12 layering cleanup) so the
router stays thin and the `hardware_nodes` table access lives in one place.
`mqtt.py` still writes directly to the table on heartbeat ingest (per-message
hot-path optimization documented in the AGENTS.md V20 exception).
"""

import re

from ..db import get_db
from ..mqtt import mqtt_publish

# Path segments must stay inside the per-node namespace. A caller that set
# `topic: "sporeprint/OTHER_NODE/cmd/heater"` previously bypassed it entirely.
NODE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
CHANNEL_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


async def list_nodes() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM hardware_nodes ORDER BY last_seen DESC")
        return [dict(r) for r in await cursor.fetchall()]


async def get_node(node_id: str) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM hardware_nodes WHERE node_id = ?", (node_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def send_command(node_id: str, command: dict) -> str:
    """Publish a command to a specific node, returning the topic used.

    Caller must have already validated `node_id`. This helper strips any
    caller-supplied `topic` and `channel` from `command` to prevent injection,
    then composes the canonical `sporeprint/{node}/cmd/{channel}` topic itself.
    """
    command = dict(command)
    command.pop("topic", None)
    channel = command.pop("channel", None) or "config"
    if not CHANNEL_RE.match(str(channel)):
        raise ValueError("Invalid channel")
    topic = f"sporeprint/{node_id}/cmd/{channel}"
    await mqtt_publish(topic, command)
    return topic
