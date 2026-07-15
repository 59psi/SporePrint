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
the server's real subscriptions (parsed from mqtt.py), the command topics
the automation engine publishes, the plug command/state topics, and the
per-node pattern scoping.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ACL = REPO_ROOT / "config" / "mosquitto" / "acl.conf"
MQTT_PY = REPO_ROOT / "server" / "app" / "mqtt.py"
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


def test_server_can_make_every_subscription_the_code_makes():
    """Subscriptions are parsed from mqtt.py — if the code adds one, this
    test forces the ACL to grant it."""
    subs = re.findall(r'client\.subscribe\(\s*"([^"]+)"', MQTT_PY.read_text())
    assert subs, "no client.subscribe() calls parsed from mqtt.py — parser broken"
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
    ):
        assert can_publish("server", topic), f"server denied publish to {topic}"


def test_server_can_publish_plug_commands():
    # smart_plugs.py: shellies/<id>/relay/0/command, <prefix>/cmnd/POWER
    for topic in (
        "shellies/humidifier/relay/0/command",
        "tasmota/heater/cmnd/POWER",
    ):
        assert can_publish("server", topic), (
            f"server denied publish to {topic} — plug rules fire into a "
            f"broker that drops them"
        )


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


def test_plug_account_cannot_touch_node_topics():
    """Blast-radius isolation: a compromised plug credential must not reach
    the sporeprint/ namespace."""
    assert not can_publish("sp-3p", "sporeprint/relay-01/cmd/fae")
    assert not can_subscribe("sp-3p", "sporeprint/#")


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
    ):
        assert can_publish(node, topic), f"node denied publish to its own {topic}"
    assert can_subscribe(node, f"sporeprint/{node}/cmd/#")
    # …and never a sibling's:
    assert not can_publish(node, "sporeprint/relay-01/telemetry")
    assert not can_subscribe(node, "sporeprint/relay-01/cmd/#")
    assert not can_subscribe(node, "sporeprint/#")


# ── provisioning actually creates the accounts the ACL names ─────────────


def test_setup_provisions_the_accounts():
    setup = SETUP_SH.read_text()
    assert "mosquitto_passwd -b config/mosquitto/passwd server" in setup, (
        "setup.sh no longer provisions the `server` broker user"
    )
    assert "sp-3p" in setup, (
        "setup.sh no longer provisions the sp-3p (smart plug) broker user — "
        "plugs cannot authenticate without it"
    )


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
