"""Firmware ⇄ Pi wire-contract test.

The bug class this guards against: every layer reads wire fields by string
literal, and a name mismatch does NOT throw. ``payload.get("temperature")``
when the firmware emits ``temp_c`` silently yields None and the value renders
as 0 or vanishes. That single mistake, repeated, is why the cloud's fleet tiles
read 0°F on every chamber, why the metric-alert engine never evaluated a
reading, and why weight_g/door_open shipped persisted nowhere.

The emitter contract is derived from the FIRMWARE SOURCE at test time — the
``doc["..."]`` keys are parsed out of ``firmware/src/**/*.cpp`` — never from a
hand-maintained list, which could rot exactly the way the consumers did.
Consumer allowlists are then asserted to be a subset of what the firmware
actually emits, and (modulo an explicit ignore-list) that nothing emitted is
silently dropped.

What this canNOT catch, so don't read it as more than it is:
  * Dynamically-keyed emissions — the dim-level report writes
    ``doc[channel.name]``, which is not a string literal in the source.
  * Topic ROUTING bugs — a scene published to cmd/config instead of cmd/scene
    is a correct key on the wrong topic. Covered separately by the routing
    tests in test_automation_routing.py.
  * Value-type drift (bool vs float) — the parser sees names, not types.
  * The HTTP wire shape of /api/vision/frame (multipart vs raw body).
  * Consumers in the cloud repo. The sets built here are the ground truth that
    repo should assert against too.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = REPO_ROOT / "firmware"
NODE_MAIN = FIRMWARE / "src" / "node" / "main.cpp"
SERVER_APP = REPO_ROOT / "server" / "app"

# doc["key"] / o["key"] / chans["key"] assignments in the publishers.
_KEY_RE = re.compile(r'\b(?:doc|o|obj|cam|chans|sensors)\[\s*"([^"]+)"\s*\]')


def _read(path: Path) -> str:
    # A guard that silently skips is not a guard. If the firmware tree moved,
    # this test must be repointed, never deleted.
    assert path.is_file(), f"{path} missing — firmware tree moved?"
    return path.read_text()


def _function_body(source: str, signature: str) -> str:
    """Brace-balanced function body. Fine for firmware code whose string
    literals contain no braces (true today; if that changes, this parse needs
    revisiting — it does not mean the contract broke)."""
    start = source.find(signature)
    assert start != -1, f"{signature!r} not found — firmware refactored?"
    brace = source.index("{", start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[brace : i + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


# ── the emitter contract, parsed from firmware source ───────────────────


def emitted_telemetry_keys() -> set[str]:
    """Every key publish_telemetry() can put on the telemetry topic."""
    keys = set(_KEY_RE.findall(_function_body(_read(NODE_MAIN), "static void publish_telemetry()")))
    assert keys, "no doc[...] keys parsed from publish_telemetry — parser broken"
    return keys


def firmware_channel_names() -> set[str]:
    """Channel names from personality.h. These are MQTT command routing keys:
    the node matches cmd/<channel> exactly and drops anything else."""
    src = _read(FIRMWARE / "lib" / "sp_core" / "personality.h")
    names: set[str] = set()
    for group in re.findall(r"names\[4\]\s*=\s*\{([^}]+)\}", src):
        names |= set(re.findall(r'"([^"]+)"', group))
    assert names, "no channel names parsed from personality.h"
    return names


def firmware_scene_names() -> set[str]:
    names = set(re.findall(r'\{\s*"([a-z_0-9]+)"\s*,\s*\{', _read(FIRMWARE / "lib" / "sp_core" / "scene_table.h")))
    assert names, "no scenes parsed from scene_table.h"
    return names


def weather_virtual_keys() -> set[str]:
    """outdoor_*/forecast_* keys the Pi synthesizes into readings before rule
    evaluation. Not firmware-emitted, but legal for a rule to threshold on."""
    m = re.search(r"for key in \(([^)]+)\)", _read(SERVER_APP / "mqtt.py"), re.S)
    assert m, "weather enrichment tuple not found in mqtt.py"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


# ── direction 1: every consumer allowlist ⊆ the emitter contract ────────


def test_sensor_fields_are_all_emitted():
    """SENSOR_FIELDS is the persistence allowlist. A name in it the firmware
    never emits is a dead read: the column simply never appears."""
    from app.telemetry.service import SENSOR_FIELDS

    emitted = emitted_telemetry_keys()
    dead = set(SENSOR_FIELDS) - emitted
    assert not dead, (
        f"SENSOR_FIELDS reads names the firmware never emits: {sorted(dead)}. "
        f"Firmware emits: {sorted(emitted)}"
    )


def test_grafana_sensor_map_is_all_persisted():
    """The exporter reads telemetry_readings, so its map must be a subset of
    the persistence allowlist (which the test above pins to the firmware)."""
    from app.integrations.grafana.exporter import _SENSOR_MAP
    from app.telemetry.service import SENSOR_FIELDS

    dead = set(_SENSOR_MAP) - set(SENSOR_FIELDS)
    assert not dead, f"grafana exports sensors that are never persisted: {sorted(dead)}"


def test_grafana_sql_literal_matches_sensor_map():
    """The exporter repeats its sensor list as a SQL string literal, which can
    drift from _SENSOR_MAP without any import breaking."""
    from app.integrations.grafana.exporter import _SENSOR_MAP

    m = re.search(r"sensor IN \(([^)]+)\)", _read(SERVER_APP / "integrations" / "grafana" / "exporter.py"))
    assert m, "sensor IN (...) literal not found in the grafana exporter"
    sql_set = set(re.findall(r"'([^']+)'", m.group(1)))
    assert sql_set == set(_SENSOR_MAP), (
        f"grafana SQL literal drifted from _SENSOR_MAP: "
        f"sql-only={sorted(sql_set - set(_SENSOR_MAP))}, "
        f"map-only={sorted(set(_SENSOR_MAP) - sql_set)}"
    )


def test_automation_engine_reads_are_emitted():
    """Every readings.get("...") and the inline audit list in the engine must
    name keys that actually exist on the wire."""
    src = _read(SERVER_APP / "automation" / "engine.py")
    valid = emitted_telemetry_keys() | weather_virtual_keys()

    read_names = set(re.findall(r'readings\.get\(\s*"([^"]+)"', src))
    audit_lists = re.findall(r"for k in\s*\[([^\]]+)\]", src)
    assert audit_lists, "audit-list comprehension not found in engine.py"
    for lst in audit_lists:
        read_names |= set(re.findall(r'"([^"]+)"', lst))

    dead = read_names - valid
    assert not dead, (
        f"the automation engine reads names that are never on the wire: {sorted(dead)}"
    )


def test_builtin_rule_templates_match_firmware():
    """Seeded rules must reference sensors, channels, and scenes the firmware
    answers to. A seeded rule naming a channel the node drops is a no-op that
    still logs 'fired' — the exact failure the `mister`/`aux` split caused."""
    from app.automation.templates import BUILTIN_RULES

    valid_sensors = emitted_telemetry_keys() | weather_virtual_keys()
    valid_channels = firmware_channel_names()
    valid_scenes = firmware_scene_names()

    def sensors_of(cond) -> set[str]:
        out: set[str] = set()
        if cond is None:
            return out
        if cond.threshold is not None:
            out.add(cond.threshold.sensor)
        if cond.compound is not None:
            for c in cond.compound.conditions:
                out |= sensors_of(c)
        return out

    for rule in BUILTIN_RULES:
        dead = sensors_of(rule.condition) - valid_sensors
        assert not dead, f"rule {rule.name!r} thresholds on unknown sensor(s) {sorted(dead)}"
        if rule.action.channel is not None:
            assert rule.action.channel in valid_channels, (
                f"rule {rule.name!r} targets channel {rule.action.channel!r}; "
                f"the firmware only answers to {sorted(valid_channels)}"
            )
        if rule.action.scene is not None:
            assert rule.action.scene in valid_scenes, (
                f"rule {rule.name!r} uses scene {rule.action.scene!r}; "
                f"the firmware only knows {sorted(valid_scenes)}"
            )


def test_mqtt_ingest_reads_are_emitted():
    """Every literal key mqtt.py pulls off a firmware payload must exist in a
    firmware publisher. `kind` is a tolerated defensive fallback: it is read
    before `type` in an `or` chain, is never emitted, and so cannot mask."""
    TOLERATED = {"kind"}
    src = _read(SERVER_APP / "mqtt.py")

    emitted: set[str] = set()
    for path in (NODE_MAIN, FIRMWARE / "src" / "cam" / "main.cpp"):
        emitted |= set(_KEY_RE.findall(_read(path)))
    for lib in ("mqtt_link.cpp", "ota_service.cpp", "coredump_uploader.cpp", "log_forward.cpp"):
        emitted |= set(_KEY_RE.findall(_read(FIRMWARE / "lib" / "sp_device" / lib)))
    assert len(emitted) > 20, f"suspiciously few emitted keys parsed: {sorted(emitted)}"

    reads = set(re.findall(r'\bpayload\.get\(\s*"([^"]+)"', src))
    reads |= set(re.findall(r'\be\.get\(\s*"([^"]+)"', src))
    dead = reads - emitted - TOLERATED
    assert not dead, f"mqtt.py reads payload keys no firmware publisher emits: {sorted(dead)}"


# ── direction 2: nothing the firmware emits is silently dropped ─────────


def test_no_emitted_telemetry_field_is_dropped():
    """Every telemetry key the firmware can emit must be persisted, or listed
    here with a reason. When firmware grows a sensor field this fails until
    someone either persists it or consciously ignores it — which is exactly the
    decision that got skipped when weight_g and door_open shipped unpersisted.
    """
    from app.telemetry.service import SENSOR_FIELDS

    IGNORED = {
        # Uptime-seconds stamp. The server replaces it with wall-clock time
        # (mqtt.py clamps anything before 2020), so it is consumed, not stored.
        "ts",
        # Uncalibrated HX711 counts, emitted only when the scale has no
        # calibration yet. The firmware marks it tolerated-not-stored: it
        # exists so an operator can watch the tare/calibrate flow move the
        # needle. The units are meaningless until calibration, so storing it
        # as a reading would be storing a number that means nothing.
        "scale_raw",
    }
    dropped = emitted_telemetry_keys() - set(SENSOR_FIELDS) - IGNORED
    assert not dropped, (
        f"the firmware emits telemetry field(s) nothing persists: {sorted(dropped)}. "
        f"Either add them to SENSOR_FIELDS (and decide bool/float handling) or add "
        f"them to IGNORED with a justification."
    )
