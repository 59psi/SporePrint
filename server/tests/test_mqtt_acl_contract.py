"""Broker ACL ⇄ code contract: every topic the system uses must be granted.

Mosquitto denies unauthorized publishes and subscriptions SILENTLY — the
client gets no error, messages just don't flow. That made the perfect trap:
through v4.2.0 the ACL had no `user server` block at all, so the account
setup.sh actually provisions fell through to the per-node pattern grants and
a freshly-built Pi could neither hear its nodes nor command them. No test,
no log line, no error anywhere — only a physical bench build would have
caught it.

This test parses config/mosquitto/acl.conf, implements Mosquitto's topic-
matching rules, and asserts the grants cover exactly what the code does:
the server's real subscriptions (recorded from the start_mqtt loop), the
command topics the automation engine publishes, the plug command/state
topics, and the per-node pattern scoping.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from app.automation.smart_plugs import handle_plug_message, send_plug_command
from app.config import settings
from app.db import get_db
from app.mqtt import (
    RESERVED_NODE_IDS,
    _handle_message,
    is_reserved_node_id,
    is_service_account,
    purge_reserved_nodes,
)
from tests._pi_b1_mqtt import FakeBroker, RecordingSio, node_ids, run_mqtt_loop

REPO_ROOT = Path(__file__).resolve().parents[2]
ACL = REPO_ROOT / "config" / "mosquitto" / "acl.conf"
SETUP_SH = REPO_ROOT / "setup.sh"
ADD_NODE_SH = REPO_ROOT / "scripts" / "add-node-mqtt-user.sh"


# ── minimal, faithful Mosquitto ACL model ────────────────────────────────


def _parse_acl() -> tuple[dict[str, list[tuple[str, str]]], list[tuple[str, str]]]:
    """Returns ({user: [(access, filter), ...]}, [(access, pattern_filter), ...])."""
    users: dict[str, list[tuple[str, str]]] = {}
    patterns: list[tuple[str, str]] = []
    current: str | None = None
    for raw in ACL.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("user "):
            current = line.split(None, 1)[1]
            users.setdefault(current, [])
        elif line.startswith("topic "):
            parts = line.split()
            access, flt = (parts[1], parts[2]) if len(parts) == 3 else ("readwrite", parts[1])
            assert current is not None, f"topic line before any user: {line!r}"
            users[current].append((access, flt))
        elif line.startswith("pattern "):
            parts = line.split()
            access, flt = (parts[1], parts[2]) if len(parts) == 3 else ("readwrite", parts[1])
            patterns.append((access, flt))
    return users, patterns


def _filter_matches(flt: str, topic: str) -> bool:
    """MQTT filter → concrete topic match (+ single level, # multi tail)."""
    f, t = flt.split("/"), topic.split("/")
    for i, seg in enumerate(f):
        if seg == "#":
            return True
        if i >= len(t):
            return False
        if seg != "+" and seg != t[i]:
            return False
    return len(f) == len(t)


def _filter_covers(flt: str, sub: str) -> bool:
    """Does an ACL filter cover a requested SUBSCRIPTION filter?"""
    f, s = flt.split("/"), sub.split("/")
    for i, seg in enumerate(f):
        if seg == "#":
            return True
        if i >= len(s):
            return False
        if s[i] == "#":
            return False  # request is broader than the grant
        if seg != "+" and seg != s[i]:
            return False
    return len(f) == len(s)


def _grants_for(user: str) -> list[tuple[str, str]]:
    users, patterns = _parse_acl()
    grants = list(users.get(user, []))
    grants += [(a, f.replace("%u", user).replace("%c", user)) for a, f in patterns]
    return grants


def can_publish(user: str, topic: str) -> bool:
    return any(
        a in ("write", "readwrite") and _filter_matches(f, topic)
        for a, f in _grants_for(user)
    )


def can_subscribe(user: str, sub: str) -> bool:
    return any(
        a in ("read", "readwrite") and _filter_covers(f, sub)
        for a, f in _grants_for(user)
    )


# ── the server account ───────────────────────────────────────────────────


async def _server_subscriptions(monkeypatch) -> list[str]:
    """Every subscription the real start_mqtt loop makes on connect."""
    broker = FakeBroker([])
    await run_mqtt_loop(monkeypatch, broker)
    assert broker.subscriptions, "the loop subscribed to nothing"
    return broker.subscriptions


async def test_server_can_make_every_subscription_the_code_makes(monkeypatch):
    """Recorded from the loop itself, the $SYS broker-stats topics included
    (aiomqtt does not raise on a refused SUBACK, so a missing grant leaves
    GET /api/health/detail/mqtt at {}): if the code adds a subscription,
    this test forces the ACL to grant it."""
    subs = await _server_subscriptions(monkeypatch)
    assert any(s.startswith("$SYS/") for s in subs)
    denied = [s for s in subs if not can_subscribe("server", s)]
    assert not denied, (
        f"the server subscribes to {denied} but the ACL denies it — Mosquitto "
        f"denies silently, so this ships as 'the Pi hears nothing'"
    )


def test_server_can_publish_node_commands():
    # Engine command routing (automation/engine.py): cmd/<channel>, cmd/scene, cmd/config
    for topic in (
        "sporeprint/relay-01/cmd/fae",
        "sporeprint/relay-01/cmd/aux",
        "sporeprint/light-01/cmd/scene",
        "sporeprint/climate-01/cmd/config",
        # mqtt.py's store-then-ack for a node's panic dump
        "sporeprint/climate-01/cmd/coredump_ack",
    ):
        assert can_publish("server", topic), f"server denied publish to {topic}"


def test_server_can_publish_plug_commands():
    # smart_plugs.py: shellies/<id>/relay/0/command, <prefix>/cmnd/POWER,
    # and a Shelly Gen2+ JSON-RPC frame on <prefix>/rpc (prefix shellies/<role>)
    for topic in (
        "shellies/humidifier/relay/0/command",
        "tasmota/heater/cmnd/POWER",
        "shellies/humidifier/rpc",
    ):
        assert can_publish("server", topic), (
            f"server denied publish to {topic} — plug rules fire into a "
            f"broker that drops them"
        )


@pytest.mark.parametrize("plug_type,prefix", [
    ("shelly", "shellies/humidifier"),
    ("shelly_gen2", "shellies/humidifier"),
    ("tasmota", "tasmota/heater"),
])
async def test_every_plug_command_the_code_builds_is_granted(mock_mqtt_raw, plug_type, prefix):
    """Drive the real send_plug_command (and the Gen2 status query) per plug
    type: every topic it publishes must be one the server account may write."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO smart_plugs (plug_id, plug_type, mqtt_topic_prefix, name) "
            "VALUES ('plug-x', ?, ?, 'x')", (plug_type, prefix))
        await db.commit()
    for state in ("on", "off"):
        assert await send_plug_command("plug-x", state) is True
    if prefix.startswith("shellies/"):
        await handle_plug_message(RecordingSio(), f"{prefix}/online", True)
    assert mock_mqtt_raw, "nothing was published"
    denied = sorted({t for t, _ in mock_mqtt_raw if not can_publish("server", t)})
    assert not denied, f"the ACL denies the server's plug publishes {denied}"


def test_gen2_commands_are_scoped_to_one_level_under_shellies():
    """The Gen2 grant is shellies/+/rpc, nothing wider: not a device's factory
    prefix (a top-level tree) and not a deeper prefix."""
    for topic in (
        "shellyplusplugs-a8032ab12345/rpc",
        "shellies/closet/humidifier/rpc",
        "sporeprint/rpc",
        "rpc",
    ):
        assert not can_publish("server", topic), f"server may publish {topic}"


# ── the smart-plug account (sp-3p) ───────────────────────────────────────


def test_plug_account_covers_what_a_plug_does():
    """A plug PUBLISHES its state/telemetry and SUBSCRIBES to its command
    topic. These are the exact topics handle_plug_message() parses."""
    for topic in (
        "shellies/humidifier/relay/0",          # state report
        "shellies/humidifier/relay/0/power",    # power report
        "tasmota/heater/stat/POWER",            # state report
        "tasmota/heater/tele/SENSOR",           # energy telemetry
    ):
        assert can_publish("sp-3p", topic), f"sp-3p denied publish to {topic}"
    for sub in (
        "shellies/humidifier/relay/0/command",
        "tasmota/heater/cmnd/POWER",
    ):
        assert can_subscribe("sp-3p", sub), f"sp-3p denied subscribe to {sub}"


async def test_plug_account_covers_what_a_gen2_shelly_does(monkeypatch):
    """A Shelly Gen2+ with its MQTT prefix set to shellies/<role> publishes
    its notifications, status, online flag and RPC replies there and
    subscribes to its own rpc / command topics (plus the shellies/command
    broadcast). sp-3p must allow all of it, and the server must hear every
    report topic handle_plug_message() parses."""
    reports = (
        "shellies/humidifier/events/rpc",       # NotifyStatus / NotifyFullStatus
        "shellies/humidifier/status/switch:0",  # Generic status update over MQTT
        "shellies/humidifier/online",           # retained online flag + LWT
        "shellies/humidifier/sporeprint/rpc",   # replies (src = <prefix>/sporeprint)
    )
    subscriptions = await _server_subscriptions(monkeypatch)
    for topic in reports:
        assert can_publish("sp-3p", topic), f"sp-3p denied publish to {topic}"
        assert any(_filter_matches(sub, topic) for sub in subscriptions), (
            f"the server never subscribes to {topic}")
    for sub in (
        "shellies/humidifier/rpc",
        "shellies/humidifier/command",
        "shellies/humidifier/command/switch:0",
        "shellies/command",
    ):
        assert can_subscribe("sp-3p", sub), f"sp-3p denied subscribe to {sub}"


def test_plug_account_is_not_widened_for_gen2_factory_prefixes():
    """A Gen2 device's factory prefix is its device id, a top-level tree.
    Granting those would need +/… wildcards that cover every two-level topic
    on the broker — so the ACL stays shellies/# and the device's prefix moves
    under it instead. A device left on its factory prefix is refused."""
    for topic in (
        "shellyplusplugs-a8032ab12345/events/rpc",
        "shellyplusplugs-a8032ab12345/online",
        "shellypro4pm-f008d1d8b8b8/status/switch:0",
    ):
        assert not can_publish("sp-3p", topic), f"sp-3p may publish {topic}"
    assert not can_subscribe("sp-3p", "shellyplusplugs-a8032ab12345/rpc")
    users, _patterns = _parse_acl()
    assert all(flt.split("/")[0] in ("shellies", "tasmota")
               for _access, flt in users["sp-3p"]), users["sp-3p"]


def test_plug_account_cannot_touch_node_topics():
    """Blast-radius isolation: a compromised plug credential must not reach
    the sporeprint/ namespace."""
    assert not can_publish("sp-3p", "sporeprint/relay-01/cmd/fae")
    assert not can_subscribe("sp-3p", "sporeprint/#")


# ── per-plug logins (scripts/add-plug-mqtt-user.sh) ─────────────────────


def test_a_per_plug_login_reaches_its_own_plug_only():
    """sp-3p is one password in every plug, readable from an unprotected
    plug's web page: it switches every other plug and fakes their state. A
    login named after the plug's topic level is scoped to that tree."""
    for topic in ("tasmota/heater/stat/POWER", "tasmota/heater/stat/RESULT",
                  "tasmota/heater/tele/SENSOR", "tasmota/heater/tele/LWT",
                  "shellies/heater/relay/0", "shellies/heater/relay/0/power",
                  "shellies/heater/events/rpc", "shellies/heater/status/switch:0",
                  "shellies/heater/online", "shellies/heater/sporeprint/rpc"):
        assert can_publish("heater", topic), topic
    for sub in ("tasmota/heater/cmnd/POWER", "shellies/heater/rpc",
                "shellies/heater/relay/0/command", "shellies/heater/command/#"):
        assert can_subscribe("heater", sub), sub
    for topic in ("tasmota/humidifier/stat/POWER", "tasmota/humidifier/cmnd/POWER",
                  "shellies/humidifier/relay/0", "shellies/humidifier/rpc",
                  "sporeprint/relay-01/cmd/fae"):
        assert not can_publish("heater", topic), topic
    for sub in ("tasmota/#", "shellies/#", "tasmota/humidifier/cmnd/POWER"):
        assert not can_subscribe("heater", sub), sub
    # The shared login keeps working for plugs already set up with it.
    assert can_publish("sp-3p", "tasmota/humidifier/stat/POWER")
    _users, patterns = _parse_acl()
    assert ("readwrite", "tasmota/%u/#") in patterns and ("readwrite", "shellies/%u/#") in patterns


async def test_plug_logins_never_become_nodes_and_stay_plugs(monkeypatch):
    """The per-node patterns apply to every login: a plug login could post
    sporeprint/<its name>/… and register as a node feeding the rules. Listed
    in SPOREPRINT_MQTT_PLUG_USERS, it is reserved like a service account,
    while its plug frames still make a plug."""
    monkeypatch.setattr(settings, "mqtt_plug_users", "heater, Humidifier")
    assert is_reserved_node_id("HEATER") and is_reserved_node_id("humidifier")
    assert not is_service_account("heater")
    sio = RecordingSio()
    await _handle_message(sio, "sporeprint/heater/status/heartbeat", {"type": "relay", "ip": "10.0.0.9"})
    await _handle_message(sio, "sporeprint/humidifier/telemetry", {"temp_f": 50.0, "ts": 5000})
    assert await node_ids() == []
    await _handle_message(sio, "tasmota/heater/stat/POWER", "ON")
    async with get_db() as db:
        rows = await (await db.execute("SELECT plug_id FROM smart_plugs")).fetchall()
    assert [r["plug_id"] for r in rows] == ["plug-heater"]


async def test_service_accounts_never_become_plugs(monkeypatch):
    """The per-plug patterns let every login post under tasmota/<its name>/
    and shellies/<its name>/: a service account's frames there are dropped."""
    monkeypatch.setattr(settings, "mqtt_username", "pi-core")
    sio = RecordingSio()
    for account in (*sorted(RESERVED_NODE_IDS), "pi-core", "SP-Telemetry"):
        await _handle_message(sio, f"tasmota/{account}/stat/POWER", "ON")
        await _handle_message(sio, f"shellies/{account}/relay/0", "on")
        await _handle_message(sio, f"shellies/{account}/online", "true")
    async with get_db() as db:
        rows = await (await db.execute("SELECT plug_id FROM smart_plugs")).fetchall()
    assert rows == [] and sio.events == []


# ── per-node pattern scoping ─────────────────────────────────────────────


def test_node_is_scoped_to_its_own_namespace():
    """Username == node_id; the %u patterns must let a node run its whole
    publish surface and read its own commands — and nothing of a sibling."""
    node = "climate-01"
    for topic in (
        f"sporeprint/{node}/telemetry",
        f"sporeprint/{node}/telemetry/fae",
        f"sporeprint/{node}/status/heartbeat",
        f"sporeprint/{node}/health",
        f"sporeprint/{node}/alert",
        f"sporeprint/{node}/ota",
        # log_forward.cpp batches SP_LOG lines here (→ node_logs table)
        f"sporeprint/{node}/logs",
        # coredump_uploader.cpp streams the panic dump here; older firmware
        # then ERASES the partition — a denied (silently dropped) chunk loses
        # it for good. (Current firmware waits for cmd/coredump_ack.)
        f"sporeprint/{node}/coredump/chunk",
    ):
        assert can_publish(node, topic), f"node denied publish to its own {topic}"
    assert can_subscribe(node, f"sporeprint/{node}/cmd/#")
    # The Pi's coredump ack reaches the node through that cmd/# grant.
    assert can_subscribe(node, f"sporeprint/{node}/cmd/coredump_ack")
    # …and never a sibling's:
    assert not can_publish(node, "sporeprint/relay-01/telemetry")
    assert not can_publish(node, "sporeprint/relay-01/logs")
    assert not can_publish(node, "sporeprint/relay-01/coredump/chunk")
    assert not can_subscribe(node, "sporeprint/relay-01/cmd/#")
    assert not can_subscribe(node, "sporeprint/#")


FIRMWARE = REPO_ROOT / "firmware"


def _firmware_topic_suffixes() -> set[str]:
    """Every `topic("<suffix>")` the firmware builds (MqttLink::topic()
    prefixes `sporeprint/<node_id>/`)."""
    suffixes: set[str] = set()
    for sub in ("lib", "src"):
        for path in (FIRMWARE / sub).rglob("*"):
            if path.suffix not in (".cpp", ".h", ".hpp"):
                continue
            suffixes.update(re.findall(r'\btopic\("([^"]*)"\)', path.read_text(errors="replace")))
    return suffixes


def test_every_firmware_topic_is_granted_to_the_node():
    """Parsed from the firmware itself: adding a new node publish topic
    without granting it in acl.conf fails here instead of shipping as a
    feature that silently never reaches the Pi."""
    node = "climate-01"
    suffixes = _firmware_topic_suffixes()
    assert {"telemetry", "status", "logs", "coredump/chunk"} <= suffixes, (
        f"firmware topic parser broken — found only {sorted(suffixes)}"
    )
    for suffix in sorted(suffixes):
        topic = f"sporeprint/{node}/{suffix}"
        if suffix.endswith("/"):
            topic += "fae"  # dynamic per-channel topic, e.g. telemetry/<ch>
        if suffix == "cmd" or suffix.startswith("cmd/"):
            assert can_subscribe(node, topic), f"node denied subscribe to {topic}"
        else:
            assert can_publish(node, topic), f"node denied publish to {topic}"


# ── provisioning actually creates the accounts the ACL names ─────────────


def test_setup_provisions_the_accounts():
    setup = SETUP_SH.read_text()
    # Both paths: the broker image (docker) and the host's mosquitto_passwd.
    assert 'server "$MQTT_SERVER_PASS" sp-3p "$MQTT_3P_PASS"' in setup, (
        "setup.sh no longer provisions the `server` broker user"
    )
    assert 'sp_host_passwd_set config/mosquitto/passwd server "$MQTT_SERVER_PASS"' in setup, (
        "setup.sh no longer provisions the `server` broker user without docker"
    )
    assert "sp-3p" in setup, (
        "setup.sh no longer provisions the sp-3p (smart plug) broker user — "
        "plugs cannot authenticate without it"
    )


def test_install_provisions_the_accounts():
    """install.sh is the supported Pi installer — it must create the same
    two accounts the ACL names (in place, keeping per-node users)."""
    body = (REPO_ROOT / "install.sh").read_text()
    assert 'server "$MQTT_PASS" sp-3p "$MQTT_3P_PASS"' in body
    assert 'grep -q "^server:" /work/passwd' in body


def test_per_node_credential_script_exists():
    assert ADD_NODE_SH.is_file(), (
        "scripts/add-node-mqtt-user.sh missing — with allow_anonymous false "
        "there is no other way for an ESP32 node to get onto the broker"
    )
    body = ADD_NODE_SH.read_text()
    assert "mosquitto_passwd" in body and "node_id" in body.lower()


def test_broker_actually_requires_auth():
    """The whole model rests on allow_anonymous false — if someone flips it
    back on 'to debug', every device on the LAN can drive the actuators."""
    conf = (REPO_ROOT / "config" / "mosquitto" / "mosquitto.conf").read_text()
    assert "allow_anonymous false" in conf


# ── service accounts never become nodes (final review, security) ─────────
#
# The per-node `pattern` grants apply to EVERY broker user, service accounts
# included: sp-3p (whose password lives on third-party plug firmware) can
# publish sporeprint/sp-3p/{status,telemetry,alert}. The server upserted any
# status sender into hardware_nodes and fed any telemetry to the rules
# engine, so a leaked plug credential could register a node, claim a node
# type and drive the heater/humidifier through automation. Frames under a
# service account's name are dropped, and those ids can never be registered.

ROTATE_SH = REPO_ROOT / "scripts" / "rotate-mqtt-creds.sh"


def _service_accounts() -> set[str]:
    """Every non-node broker user: the ACL's `user` blocks plus the shared
    accounts the rotation script manages."""
    users, _patterns = _parse_acl()
    found = set(users)
    m = re.search(r"targets=\(([a-z0-9_ -]+)\)", ROTATE_SH.read_text())
    assert m, "rotate-mqtt-creds.sh no longer lists its default accounts"
    found |= set(m.group(1).split())
    return found


def test_every_service_account_is_a_reserved_node_id():
    accounts = _service_accounts()
    assert {"server", "sp-3p", "sp-cmd", "sp-telemetry"} <= accounts
    missing = accounts - set(RESERVED_NODE_IDS)
    assert not missing, (
        f"broker service account(s) {sorted(missing)} can publish under "
        "sporeprint/<name>/ via the per-node patterns but are not in "
        "app.mqtt.RESERVED_NODE_IDS"
    )


def test_add_node_script_refuses_exactly_the_reserved_ids():
    """add-node-mqtt-user.sh gives its argument a fresh password and reloads
    the broker. For a service account that locks the real owner out (the Pi
    server, or every smart plug), so the script refuses every id the server
    reserves, through the shared sp_service_account (which also covers the
    configured SPOREPRINT_MQTT_USERNAME)."""
    lib = (REPO_ROOT / "scripts" / "lib" / "broker.sh").read_text()
    body = re.search(r"^sp_service_account\(\) \{\n(.*?)^\}", lib, re.M | re.S)
    assert body, "scripts/lib/broker.sh no longer defines sp_service_account"
    m = re.search(r'for account in ([a-z0-9_ -]+) "\$server_user"', body.group(1))
    assert m, "sp_service_account no longer lists the service accounts"
    assert set(m.group(1).split()) == set(RESERVED_NODE_IDS)
    assert re.search(r'sp_service_account "\$ROOT" "\$NODE_ID"', ADD_NODE_SH.read_text())


async def test_service_accounts_never_become_nodes(monkeypatch):
    reached: list[str] = []

    async def _spy(node_id, readings, sio=None, **kwargs):
        reached.append(f"rules:{node_id}")

    async def _forward(*args, **kwargs):
        reached.append("forwarded")

    async def _notify(*args, **kwargs):
        reached.append("notified")

    monkeypatch.setattr("app.automation.engine.evaluate_rules", _spy)
    monkeypatch.setattr("app.mqtt.forward_telemetry", _forward)
    monkeypatch.setattr("app.mqtt.forward_event", _forward)
    monkeypatch.setattr("app.mqtt.forward_component_health", _forward)
    monkeypatch.setattr("app.mqtt.notify", _notify)
    sio = RecordingSio()
    for account in sorted(RESERVED_NODE_IDS):
        base = f"sporeprint/{account}"
        await _handle_message(sio, f"{base}/status/heartbeat",
                              {"type": "relay", "roles": ["relay"], "ip": "10.0.0.66"})
        await _handle_message(sio, f"{base}/status", {"status": "online"})
        await _handle_message(sio, f"{base}/health", {"channels": {"heater": {}}})
        await _handle_message(sio, f"{base}/telemetry", {"temp_f": 50.0, "ts": 5000})
        await _handle_message(sio, f"{base}/telemetry/heater", {"state": "on"})
        await _handle_message(sio, f"{base}/alert", {"type": "temperature", "value": 99})
        await _handle_message(sio, f"{base}/ota", {"status": "start"})
    assert await node_ids() == []
    assert reached == []
    assert sio.events == []
    # A real node's frames still register it.
    await _handle_message(sio, "sporeprint/relay-01/status/heartbeat",
                          {"type": "relay", "ip": "10.0.0.5"})
    assert await node_ids() == ["relay-01"]


def test_reserved_id_check_is_case_insensitive_and_covers_the_mqtt_user(monkeypatch):
    monkeypatch.setattr(settings, "mqtt_username", "pi-core")
    assert is_reserved_node_id("SP-3P")
    assert is_reserved_node_id("Server")
    assert is_reserved_node_id("pi-core")
    assert not is_reserved_node_id("climate-01")
    assert not is_reserved_node_id("sp-3p-plug")


async def test_rows_registered_before_the_filter_are_purged(monkeypatch):
    """Service accounts (any case), the server's own login and the per-plug
    logins an older server registered as nodes are removed; real nodes stay."""
    monkeypatch.setattr(settings, "mqtt_username", "pi-core")
    monkeypatch.setattr(settings, "mqtt_plug_users", "heater")
    async with get_db() as db:
        for node_id in ("sp-3p", "Server", "pi-core", "heater", "climate-01"):
            await db.execute("INSERT INTO hardware_nodes (node_id, node_type, last_seen) "
                             "VALUES (?, 'relay', 1)", (node_id,))
        await db.commit()
    assert await purge_reserved_nodes() == 4
    assert await node_ids() == ["climate-01"]
    assert await purge_reserved_nodes() == 0


def test_claim_refuses_a_reserved_id(client):
    async def _preexisting_row():
        # A row registered by an older server, before the filter existed.
        async with get_db() as db:
            await db.execute("INSERT INTO hardware_nodes (node_id, node_type, last_seen) "
                             "VALUES ('sp-3p', 'relay', 1)")
            await db.commit()

    asyncio.run(_preexisting_row())
    r = client.post("/api/hardware/claim", json={"node_id": "sp-3p"})
    assert r.status_code == 400
    assert "reserved" in r.json()["detail"].lower()
