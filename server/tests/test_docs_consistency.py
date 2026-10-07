"""The docs must describe the code, firmware and BOM that actually ship.

Every check here pins a claim that had drifted before the 2026-09 docs pass
(docs#2/#10-#13/#15/#16/#18/#19/#22/#24/#30, srv-auto#13, srv-hw#9/#15,
deps-infra#11/#21, fw-node#13/#15, fw-drivers-cam#15/#16): tier prices,
wiring-diagram labels, MQTT topics that never existed, the Tasmota FullTopic,
the S3 pin map, the secure-boot recipe, the Grafana port. When one fails, fix
the doc (or the code) so the two agree again; don't loosen the check.
"""

import inspect
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.automation import templates as rule_templates
from app.automation.templates import BUILTIN_RULES
from app.builder.hardware_guides import TIERS, TIER_ALL, TIER_RECOMMENDED
from app.chambers.models import ChamberCreate, ChamberUpdate
from app.config import Settings
from app.db import SCHEMA
from app.hardware.service import PERIPHERAL_KEYS
from app.labels.router import _LABEL_PATHS
from app.main import app as server_app
from app.mqtt import _CLOCK_STEP_BACK_SECONDS
from app.species.models import GrowPhase
from app.species.profiles import BUILTIN_PROFILES
from app.species.wizard import recommend

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"
GUIDE = DOCS / "hardware-build-guide.md"
FW_SECURITY = DOCS / "firmware-security.md"
DUAL_REPO = DOCS / "dual-repo-architecture.md"
FW_README = ROOT / "firmware" / "README.md"
FW_DRIVERS = ROOT / "firmware" / "docs" / "drivers.md"
BROKER_README = ROOT / "config" / "mosquitto" / "README.md"
SMART_PLUGS = DOCS / "integrations" / "smart-plugs.md"
PLATFORMIO_INI = ROOT / "firmware" / "platformio.ini"
# The operator's own context file. Git-ignored (a personal file, not shipped),
# so a CI checkout has none; where it exists it is held to the same facts.
CLAUDE = ROOT / "CLAUDE.md"
SPEC = [CLAUDE] if CLAUDE.exists() else []
# Reference material split out of the old CLAUDE.md spec. Tracked, so CI
# checks the facts the spec used to carry.
SPECIES_REF = DOCS / "species-reference.md"
FEATURE_STATUS = DOCS / "feature-status.md"
AUTOMATION_RULES = DOCS / "automation-rules.md"
# Docs that state no platform, PWM spec or server size of their own; one that
# creeps in must still match the code.
_QUIET_DOCS = [SPECIES_REF, FEATURE_STATUS, AUTOMATION_RULES, *SPEC]
MODELS = ROOT / "models"
MODELS_README = MODELS / "README.md"
SVGS = sorted(DOCS.glob("*.svg"))
TIER_SVGS = sorted(DOCS.glob("wiring-tier*.svg"))
SVG_NS = "{http://www.w3.org/2000/svg}"

# Markdown an operator or contributor follows (release history excluded:
# CHANGELOG entries describe what WAS true).
CURRENT_MD = [README, AGENTS, *sorted(DOCS.rglob("*.md")), ROOT / "models" / "README.md",
              ROOT / "firmware" / "test" / "README.md", FW_README, FW_DRIVERS, BROKER_README,
              *SPEC]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _svg_labels(path: Path) -> list[str]:
    """Each <text> element's full string (tspans included)."""
    tree = ET.parse(path)
    return ["".join(el.itertext()) for el in tree.iter(f"{SVG_NS}text")]


def _section(text: str, heading_re: str) -> str:
    """The body of the first markdown section whose heading matches."""
    m = re.search(rf"^(#+) [^\n]*{heading_re}[^\n]*$", text, re.M)
    assert m, f"no section heading matching {heading_re!r}"
    level = len(m.group(1))
    rest = text[m.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


def test_docs_exist():
    assert SVGS and TIER_SVGS and GUIDE.exists() and FW_SECURITY.exists()


@pytest.mark.parametrize("svg", SVGS, ids=lambda p: p.name)
def test_every_svg_is_well_formed_xml(svg):
    ET.parse(svg)


@pytest.mark.parametrize("svg", SVGS, ids=lambda p: p.name)
def test_svg_footers_carry_no_release_number(svg):
    # All five said "SporePrint v4.0.0" through the 5.0.0 release; a
    # hard-coded number goes stale on every bump.
    stale = [t for t in _svg_labels(svg) if re.search(r"SporePrint v\d+\.\d+\.\d+", t)]
    assert not stale, f"{svg.name}: {stale}"


# ── Tier prices (docs#10) ────────────────────────────────────────────


@pytest.mark.parametrize("doc", [README, GUIDE], ids=lambda p: p.name)
def test_tier_prices_match_the_bom(doc):
    expected = {t.name: t.estimated_cost for t in TIERS}
    text = _read(doc)
    found = re.findall(r"(Bare Bones|Recommended|All the Things)\W{0,8}(~\$\d+)", text)
    assert found, f"{doc.name} states no tier price"
    wrong = [(name, price) for name, price in found if price != expected[name]]
    assert not wrong, f"{doc.name}: {wrong} — hardware_guides.py says {expected}"
    assert {name for name, _ in found} == set(expected), f"{doc.name} misses a tier price"


# ── Wiring diagrams (docs#11, docs#13, bom SVG notes) ───────────────


@pytest.mark.parametrize("svg", TIER_SVGS, ids=lambda p: p.name)
def test_only_the_camera_programmer_is_micro_usb(svg):
    # Every WROOM-32 DevKit in the BOM is the narrow USB-C board; only the
    # ESP32-CAM-MB programmer is micro-USB.
    wrong = [t for t in _svg_labels(svg) if "micro-USB" in t and not re.search(r"CAM|MB", t)]
    assert not wrong, f"{svg.name}: {wrong}"


@pytest.mark.parametrize("svg", TIER_SVGS, ids=lambda p: p.name)
def test_devkit_pins_are_named_not_numbered(svg):
    # "GND (pin 2)" is EN on a 38-pin DevKitC, and header order differs
    # between DevKit layouts — label pins by their silk-screen name only.
    numbered = [t for t in _svg_labels(svg) if re.search(r"\bpin \d+\b", t, re.I)]
    assert not numbered, f"{svg.name}: {numbered}"


def _psu_amps(tier) -> str:
    psu = next(c for c in tier.components if c.name.startswith("12V Power Supply"))
    return re.search(r"\((\d+)A,", psu.name).group(1)


@pytest.mark.parametrize("tier, svg_name", [
    (TIER_RECOMMENDED, "wiring-tier2-recommended.svg"),
    (TIER_ALL, "wiring-tier3-all-the-things.svg"),
])
def test_svg_psu_matches_the_bom(tier, svg_name):
    labels = " | ".join(_svg_labels(DOCS / svg_name))
    amps = _psu_amps(tier)
    assert f"12V {amps}A" in labels, f"{svg_name} does not show the BOM's 12V {amps}A supply"
    other = {"5", "10"} - {amps}
    for a in other:
        assert f"12V {a}A" not in labels, f"{svg_name} still shows a 12V {a}A supply"


def test_tier3_svg_shows_the_reed_on_com_and_nc():
    labels = " | ".join(_svg_labels(DOCS / "wiring-tier3-all-the-things.svg"))
    assert re.search(r"\bCOM\b", labels) and re.search(r"\bNC\b", labels)
    assert "one leg" not in labels


@pytest.mark.parametrize("svg", TIER_SVGS[1:], ids=lambda p: p.name)
def test_gate_resistors_and_flyback_part_match_the_bom(svg):
    labels = " | ".join(_svg_labels(svg))
    assert "100R" in labels or "100 Ω" in labels
    assert "UF4007" in labels, f"{svg.name}: the BOM's flyback diode is the UF4007"


@pytest.mark.parametrize("svg", TIER_SVGS[1:], ids=lambda p: p.name)
def test_tri_spectrum_wire_colours_are_shown(svg):
    labels = " | ".join(_svg_labels(svg)).lower()
    assert "blue wire" in labels
    if "tier3" in svg.name:
        assert "red wire" in labels and "green wire" in labels


@pytest.mark.parametrize("svg", TIER_SVGS, ids=lambda p: p.name)
def test_climate_node_is_a_stemma_qt_chain(svg):
    labels = " | ".join(_svg_labels(svg))
    assert "4397" in labels and "4210" in labels, f"{svg.name} misses the STEMMA QT cables"


# ── MQTT topics (docs#12) ────────────────────────────────────────────

# A topic with no node segment (sporeprint/tele/#, sporeprint/cmd/#) never
# existed: the contract is sporeprint/<node_id>/<type>[/...].
_NODELESS_TOPIC = re.compile(
    r"sporeprint/(tele|telemetry|cmd|light|status|health|alert|logs|ota)\b")


@pytest.mark.parametrize("svg", SVGS, ids=lambda p: p.name)
def test_svg_topics_carry_a_node_segment(svg):
    bad = [t for t in _svg_labels(svg) if _NODELESS_TOPIC.search(t)]
    assert not bad, f"{svg.name}: {bad}"


@pytest.mark.parametrize("doc", CURRENT_MD, ids=lambda p: str(p.relative_to(ROOT)))
def test_markdown_topics_carry_a_node_segment(doc):
    bad = _NODELESS_TOPIC.findall(_read(doc))
    assert not bad, f"{doc.relative_to(ROOT)}: {bad}"


def test_overview_svg_names_the_real_topics():
    labels = " | ".join(_svg_labels(DOCS / "wiring-overall-system.svg"))
    assert "sporeprint/<node_id>/telemetry" in labels
    assert "sporeprint/<node_id>/cmd/" in labels
    assert "tasmota/<topic>/cmnd/POWER" in labels


# ── Camera sensor (fw-drivers-cam doc note 1) ───────────────────────


@pytest.mark.parametrize("path", [README, GUIDE, AGENTS, FW_README, *SPEC, *SVGS],
                         ids=lambda p: str(p.relative_to(ROOT)))
def test_camera_sensor_is_not_ov2640_only(path):
    chunks = _svg_labels(path) if path.suffix == ".svg" else _read(path).splitlines()
    bad = [c for c in chunks if "OV2640" in c and "OV3660" not in c]
    assert not bad, f"{path.name}: {bad}"


# ── Smart plugs (docs#2, srv-auto#13, srv-hw#9, deps-infra#11) ──────

FULL_TOPIC = "tasmota/%topic%/%prefix%/"


@pytest.mark.parametrize("doc", [GUIDE, README, DOCS / "integrations" / "smart-plugs.md"],
                         ids=lambda p: p.name)
def test_tasmota_full_topic_and_credentials_are_documented(doc):
    text = _read(doc)
    assert FULL_TOPIC in text, f"{doc.name} never sets the Tasmota Full Topic"
    assert "sp-3p" in text and "SPOREPRINT_MQTT_3P_PASSWORD" in text


def test_build_guide_smart_plug_section_has_the_full_topic_and_troubleshooting_row():
    guide = _read(GUIDE)
    plugs = _section(guide, "Smart plugs")
    assert FULL_TOPIC in plugs and "sp-3p" in plugs and "Topic" in plugs
    trouble = _section(guide, "When something doesn't work")
    assert FULL_TOPIC in trouble, "no troubleshooting row for the default FullTopic"


# ── Provisioning / install (docs#16, docs#18, docs#3 docs half) ─────


@pytest.mark.parametrize("doc", [README, GUIDE], ids=lambda p: p.name)
def test_env_changes_are_applied_with_up_not_restart(doc):
    # `docker compose restart` never re-reads .env.
    assert "docker compose restart server" not in _read(doc)


def test_build_guide_installs_with_install_sh_not_setup_sh():
    pi = _section(_read(GUIDE), "The Raspberry Pi")
    assert "./install.sh" in pi
    assert "./setup.sh" not in pi


def test_build_guide_node_id_follows_the_broker_username():
    provision = _section(_read(GUIDE), "Provision each node")
    assert "accept the default" not in provision
    assert "blank" in provision and "add-node-mqtt-user.sh" in provision


# ── Firmware facts (docs#15, fw-node#15, srv-hw#15, fw-drivers-cam) ──


def _board_pin(header: str, name: str) -> str:
    text = _read(ROOT / "firmware" / "boards" / header)
    return re.search(rf"#define {name} (.+)", text).group(1).split("//")[0].strip()


def test_build_guide_documents_the_s3_pin_map_and_every_env():
    guide = _read(GUIDE)
    s3 = _section(guide, "ESP32-S3")
    header = "board_profile_esp32s3.h"
    for name in ("SP_PIN_I2C_SDA", "SP_PIN_I2C_SCL", "SP_PIN_HX711_DOUT", "SP_PIN_HX711_SCK",
                 "SP_PIN_REED", "SP_UART_CO2_RX", "SP_UART_CO2_TX"):
        pin = _board_pin(header, name)
        assert re.search(rf"\bGPIO {pin}\b", s3), f"S3 section misses {name} = GPIO {pin}"
    for pin in re.findall(r"\d+", _board_pin(header, "SP_CHANNEL_PINS")):
        assert re.search(rf"\bGPIO {pin}\b", s3), f"S3 section misses channel GPIO {pin}"
    ini = _read(ROOT / "firmware" / "platformio.ini")
    envs = [e for e in re.findall(r"^\[env:([a-z0-9_]+)\]", ini, re.M) if e != "native"]
    for env in envs:
        assert f"-e {env}" in guide, f"build guide never flashes env {env}"


def test_build_guide_documents_reed_com_nc_and_the_invert_flag():
    extras = _section(_read(GUIDE), "All the Things extras")
    assert "COM" in extras and "NC" in extras and "reed_inv" in extras
    assert "One leg of the switch" not in extras


def test_door_bring_up_tip_names_the_floating_state():
    # fw-drivers-cam#15: without the pull-up, the OPEN door floats.
    checklist = _section(_read(GUIDE), "Bring-up checklist")
    assert "flickers with the door\n   shut" not in checklist
    assert re.search(r"flickers[^.]*OPEN", checklist)


def test_camera_reset_gesture_is_documented():
    # fw-drivers-cam#16: GPIO 13, no button on the AI-Thinker board.
    guide = _read(GUIDE)
    assert "IO13" in guide and "GPIO 13" in guide


# ── Security docs (docs#19, deps-infra#21, docs#22, fw-node#13) ──────


def test_readme_security_section_matches_compose_and_auth():
    sec = _section(_read(README), "Security")
    assert "127.0.0.1" not in sec, "the broker is published on the LAN (1883/8883), not loopback"
    for public in ("/api/health", "POST /api/cloud/pair", "GET /api/provision/ca",
                   "/api/vision/frame"):
        assert public in sec, f"README Security misses public path {public}"


def test_firmware_security_doc_has_no_recipe_for_the_arduino_build():
    # The old recipe: -D flags into a nonexistent [env] base, a nonexistent
    # upload target, and v1 OTA classes. Naming them as wrong is fine;
    # instructing them is not.
    text = _read(FW_SECURITY)
    for stale in ("${env.build_flags}", "-DCONFIG_SECURE_BOOT=1", "-t signedupload",
                  "The `OTAManager` already calls", "`ota_manager.cpp` refuses",
                  "until the Pi adds a per-frame nonce"):
        assert stale not in text, f"firmware-security.md still says {stale!r}"
    assert "not supported" in text.lower()
    assert "ota_service.cpp" in text and "[esp32_base]" in text


def test_firmware_changelog_knows_the_pi_signs_topic_and_nonce():
    text = _read(ROOT / "firmware" / "CHANGELOG.md")
    unreleased = text.split("## [5.0.0]")[0]
    assert "Until the Pi adds a per-frame nonce" not in unreleased


def test_grafana_doc_points_at_the_api_port():
    text = _read(DOCS / "integrations" / "grafana" / "README.md")
    assert "chambers.local" not in text
    assert ":8000/metrics" in text


# ── Counts and paths (docs#30) ───────────────────────────────────────


def test_readme_and_agents_counts_match_the_code():
    n_species = len(BUILTIN_PROFILES)
    n_tables = len(set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA)))
    for doc in (README, AGENTS, *_QUIET_DOCS):
        text = _read(doc)
        for n in re.findall(r"(\d+) (?:built-in )?species profiles", text):
            assert int(n) == n_species, f"{doc.name} says {n} species profiles, code has {n_species}"
        for n in re.findall(r"(\d+) (?:SQLite )?tables", text):
            assert int(n) == n_tables, f"{doc.name} says {n} tables, db.py has {n_tables}"
    for doc in (README, SPECIES_REF):
        assert f"{n_species} built-in species profiles" in _read(doc), doc.name


def _server_modules() -> int:
    return sum(1 for p in (ROOT / "server" / "app").iterdir() if (p / "__init__.py").is_file())


def _api_operations() -> int:
    paths = server_app.openapi()["paths"]
    verbs = {"get", "post", "put", "patch", "delete"}
    return sum(1 for ops in paths.values() for verb in ops if verb in verbs)


# Every doc that states the server's size. dual-repo-architecture.md carried
# "17 router groups · 106 endpoints" long after the rest moved on.
_COUNT_DOCS = [README, DOCS / "data-flow.md", DUAL_REPO, DOCS / "architecture-overview.svg"]
# AGENTS.md points at README for the counts instead of repeating them.
_COUNT_OPTIONAL_DOCS = [AGENTS, *_QUIET_DOCS]


@pytest.mark.parametrize("doc", [*_COUNT_DOCS, *_COUNT_OPTIONAL_DOCS], ids=lambda p: p.name)
def test_server_module_endpoint_and_table_counts_match_the_code(doc):
    n_modules, n_ops = _server_modules(), _api_operations()
    n_tables = len(set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA)))
    text = _read(doc)
    modules = re.findall(r"\b(\d+) (?:server )?(?:modules|router groups)\b", text)
    ops = re.findall(r"\b(\d+) (?:API )?(?:operations|endpoints)\b", text)
    if doc in _COUNT_DOCS:
        assert modules or ops, f"{doc.name} no longer states the server's size — drop it from _COUNT_DOCS"
    assert all(int(n) == n_modules for n in modules), f"{doc.name}: {modules} vs {n_modules} modules"
    assert all(int(n) == n_ops for n in ops), f"{doc.name}: {ops} vs {n_ops} API operations"
    for n in re.findall(r"\b(\d+) (?:SQLite )?tables\b", text):
        assert int(n) == n_tables, f"{doc.name} says {n} tables, db.py has {n_tables}"


def test_dual_repo_doc_names_the_real_licence():
    licence = _read(ROOT / "LICENSE")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in licence
    text = _read(DUAL_REPO)
    assert "MIT License" not in text
    assert "AGPL-3.0" in text


# ── Final-review consistency (portal gestures, reed label, models) ────


def _portal_reed_invert_label() -> str:
    """The reed_inv checkbox label exactly as the setup portal renders it."""
    src = _read(ROOT / "firmware" / "lib" / "sp_device" / "wifi_provisioner.cpp")
    m = re.search(r'checkbox\("reed_inv",\s*[^,]+,\s*((?:"[^"]*"\s*)+)\)', src)
    assert m, "wifi_provisioner.cpp no longer renders a reed_inv checkbox"
    label = "".join(re.findall(r'"([^"]*)"', m.group(1)))
    return label.replace("&nbsp;", "").replace("\\u2014", "—").strip()


def _quoted_reed_labels(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return re.findall(r"[\"'](Door contact wired on its NO[^\"']*)[\"']", flat)


def test_reed_invert_label_is_quoted_as_the_portal_renders_it():
    label = _portal_reed_invert_label()
    assert "(open with the door shut)" in label
    sources = {GUIDE.name: _read(GUIDE)}
    for tier in TIERS:
        sources[tier.id] = "\n".join([*tier.setup_steps, *(c.notes for c in tier.components)])
    quoted = {name: _quoted_reed_labels(text) for name, text in sources.items()}
    assert quoted[GUIDE.name] and quoted[TIER_ALL.id], "the reed invert label is no longer quoted"
    for name, labels in quoted.items():
        assert all(q == label for q in labels), f"{name}: {labels} vs the portal's {label!r}"


def test_build_guide_camera_portal_has_no_personality_or_peripherals():
    guide = re.sub(r"\s+", " ", _read(GUIDE))
    m = re.search(r"\*\*The camera's portal\*\*([^\n]*?)\*\*Reopening", guide)
    assert m, "the camera-portal paragraph moved"
    assert re.search(r"no personality or (optional )?peripherals", m.group(1)), m.group(1)


def test_build_guide_peripherals_endpoint_lists_every_key_the_server_takes():
    provision = _section(_read(GUIDE), "Provision each node")
    body = re.search(r"/api/hardware/nodes/<node_id>/peripherals`[^`]*`(\{[^`]*\})`", provision)
    assert body, "the peripherals endpoint example moved"
    for key in PERIPHERAL_KEYS:
        assert f'"{key}"' in body.group(1), f"the build guide's peripherals body misses {key}"


def test_provision_node_teaches_the_portal_gesture_not_a_factory_reset():
    # A 10 s factory reset wipes WiFi, MQTT login, OTA password and
    # personality; the portal reopens with a 3-10 s hold and blank password
    # fields keep their saved values. The cam has no button on GPIO 13.
    text = _read(ROOT / "scripts" / "provision-node.sh")
    for stale in ("factory-reset hold 10 s", "factory-reset button", "GPIO 13 on the cam",
                  "re-enter with it"):
        assert stale not in text, f"provision-node.sh still says {stale!r}"
    assert "BOOT 3-10 s" in text and "IO13 to GND 3-10 s" in text
    assert "blank" in text


def _scad_header(name: str) -> str:
    lines = []
    for line in _read(MODELS / name).splitlines():
        if not line.startswith("//"):
            break
        lines.append(line[2:].strip())
    return " ".join(lines)


def test_switch_board_heatsinks_and_diodes_match_the_bom():
    # BOM: heatsinks are not bought (recommended above ~1 A, required above
    # ~2 A); diodes go on the relay board only (LED strips are resistive).
    readme = re.sub(r"\s+", " ", _section(_read(MODELS_README), "relay_board_mount.scad"))
    header = _scad_header("relay_board_mount.scad")
    for name, text in (("models/README.md", readme), ("relay_board_mount.scad", header)):
        assert "heatsinks for LED strips" not in text, f"{name} makes heatsinks mandatory"
        assert re.search(r"heatsinks?[^.]*optional[^.]*~1 A[^.]*~2 A[^.]*not in the BOM", text,
                         re.I), f"{name}: heatsink guidance differs from the BOM"
        assert re.search(r"DO-41 diodes? \(relay board only", text), (
            f"{name}: the lighting board takes no flyback diodes")


_CNC_M25 = re.compile(r"CNC Kitchen's M2\.5 (insert )?is (M2\.5 )?[×x] ?4")


def _line(tier, prefix):
    return next((c for c in tier.components if c.name.startswith(prefix)), None)


def test_insert_sourcing_is_one_recommendation():
    # ruthex's M2/M3/M4/M5 box has no M2.5; CNC Kitchen's M2.5 is x 4, not 5.7.
    # The docs give the one recommendation...
    for name, text in ((GUIDE.name, _read(GUIDE)), (MODELS_README.name, _read(MODELS_README))):
        flat = re.sub(r"\s+", " ", text)
        assert "B08K1BVGN9" in flat, f"{name} no longer names the ruthex M2-M5 assortment"
        assert re.search(r"separate M2\.5 [×x] 5\.7 pack", flat), f"{name}: the assortment has no M2.5"
        assert "RX-M2.5x5.7" in flat and _CNC_M25.search(flat), name
        assert "CNC Kitchen standard (M2.5" not in flat, name
        assert "covers everything except the single M5" not in flat, name
    # ...and each tier buys it as real BOM lines (no longer setup-step prose).
    for tier in TIERS:
        if tier is TIERS[0]:  # Bare Bones needs only M3 + M2.5 inserts
            m3 = _line(tier, "ruthex Heat-Set Inserts M3 x 5.7")
            assert m3 and "B08BCRZZS3" in m3.url, tier.id
        else:
            kit = _line(tier, "ruthex Heat-Set Insert Assortment M2 / M3 / M4 / M5")
            assert kit and "B08K1BVGN9" in kit.url, tier.id
        m25 = _line(tier, "Heat-Set Inserts M2.5")
        assert m25, f"{tier.id} has no separate M2.5 insert line"
        assert "RX-M2.5x5.7" in m25.notes and re.search(r"CNC Kitchen's M2\.5 x 4", m25.notes), tier.id
        assert _CNC_M25.search(re.sub(r"\s+", " ", "\n".join(tier.setup_steps))), tier.id


# ── Cabling standard (2026-10 cabling pass) ──────────────────────────

def _second_chamber(tier) -> str:
    """What a second chamber adds to a tier's price: parts_cost(2) -
    parts_cost(1). The Pi side is bought once, and kits, spools and multi-packs
    are bought in whole packs a second chamber may still draw on."""
    return f"~${round(tier.parts_cost(2) - tier.parts_cost(1))}"


@pytest.mark.parametrize("doc", [README, GUIDE], ids=lambda p: p.name)
def test_second_chamber_cost_matches_the_bom(doc):
    adds = [_second_chamber(t) for t in TIERS]
    flat = re.sub(r"\s+", " ", _read(doc))
    if doc is GUIDE:
        assert f"| A second chamber adds | {' | '.join(adds)} |" in flat, adds
    else:
        assert f"a second chamber adds {' / '.join(adds)}" in flat.lower(), (
            f"README should state what a second chamber adds as {adds}")
    assert "more than one chamber" in flat
    # The old "reusable kits" share (every shared line except the Pi side)
    # stopped meaning anything once the kits became per-chamber pack lines.
    assert "Reusable kits in the price" not in flat and "reusable kits and spools" not in flat


def _fuses(tier) -> tuple[str, str]:
    """(relay, lighting) inline fuse ratings from the BOM's power rows."""
    rows = [w.to_device for w in tier.wiring if w.to_device.startswith("Inline fuse")]
    relay = next(re.search(r"Inline fuse ([\d.]+ A)", r).group(1) for r in rows if "relay" in r)
    lighting = next(re.search(r"Inline fuse ([\d.]+ A)", r).group(1) for r in rows if "lighting" in r)
    return relay, lighting


def _has_fuse(labels: str, rating: str) -> bool:
    return bool(re.search(rf"(?<![\d.]){re.escape(rating)} fuse", labels))


@pytest.mark.parametrize("tier, svg_name", [
    (TIER_RECOMMENDED, "wiring-tier2-recommended.svg"),
    (TIER_ALL, "wiring-tier3-all-the-things.svg"),
])
def test_fuse_ratings_match_the_bom(tier, svg_name):
    relay, lighting = _fuses(tier)
    labels = " | ".join(_svg_labels(DOCS / svg_name))
    assert _has_fuse(labels, relay) and _has_fuse(labels, lighting), (svg_name, relay, lighting)
    other = {"5 A", "7.5 A"} - {lighting}
    assert not any(_has_fuse(labels, o) for o in other), f"{svg_name} shows another tier's lighting fuse"
    power = _section(_read(GUIDE), "Power and cabling")
    row = next(line for line in power.splitlines() if line.startswith("| Lighting board |"))
    col = 2 if tier is TIER_RECOMMENDED else 3
    assert f"**{lighting}** fuse" in row.split("|")[col], row
    relay_row = next(line for line in power.splitlines() if line.startswith("| Relay board |"))
    assert f"**{relay}** fuse" in relay_row.split("|")[col], relay_row


def test_wire_gauges_and_wago_parts_match_the_bom():
    rows = " ".join(f"{w.from_device} {w.to_device} {w.note}" for w in TIER_ALL.wiring)
    wagos = sorted(set(re.findall(r"WAGO 221-\d{3}", rows)))
    assert wagos == ["WAGO 221-413", "WAGO 221-415"], wagos
    assert "14 AWG" in rows and "18 AWG" in rows
    power = re.sub(r"\s+", " ", _section(_read(GUIDE), "Power and cabling"))
    for needle in (*wagos, "14 AWG", "18 AWG", "22 AWG 4-conductor"):
        assert needle in power, f"build guide §7 misses {needle}"
    names = " ".join(c.name for c in TIER_ALL.components)
    assert "18 AWG 2-Conductor" in names and "22 AWG 4-Conductor" in names
    for svg in TIER_SVGS[1:]:
        labels = " | ".join(_svg_labels(svg))
        for needle in ("221-413", "221-415", "14 AWG", "18 AWG"):
            assert needle in labels, f"{svg.name} misses {needle}"
    assert "22 AWG 4-conductor" in " | ".join(_svg_labels(DOCS / "wiring-tier3-all-the-things.svg"))


def test_hx711_cable_colours_match_the_bom():
    notes = {w.to_pin: w.note for w in TIER_ALL.wiring if w.to_device == "HX711"}
    colours = {pin: re.search(r"22/4 cable: (\w+)", note).group(1) for pin, note in notes.items()}
    extras = _section(_read(GUIDE), "All the Things extras")
    for pin, colour in colours.items():
        assert re.search(rf"\| {colour} \|", extras), f"build guide HX711 table misses {colour} ({pin})"


def test_common_ground_is_documented_everywhere():
    guide = _read(GUIDE)
    for heading in ("Wire the relay node", "Power and cabling"):
        assert "common ground" in _section(guide, heading).lower(), heading
    for svg in TIER_SVGS[1:]:
        labels = " | ".join(_svg_labels(svg))
        assert labels.count("COMMON GROUND") >= 2, f"{svg.name}: show the common ground on both boards"
        assert "J1 −" in labels


def _strip_outlets(tier) -> str:
    strip = _line(tier, "Surge Protector Power Strip")
    assert strip, f"{tier.id} has no surge strip"
    m = re.search(r"(\d+) outlets( \+ 2 USB-A)?", strip.name)
    return m.group(1) + (" + 2 USB-A" if m.group(2) else "")


def test_power_strip_sizes_match_the_bom():
    power = _section(_read(GUIDE), "Power and cabling")
    row = next(line for line in power.splitlines() if "the BOM's strip" in line)
    for tier, svg, cell in zip(TIERS, TIER_SVGS, row.split("|")[2:5]):
        outlets = _strip_outlets(tier)
        assert re.search(rf"→ {re.escape(outlets.replace(' + ', ' outlets + ', 1))}"
                         rf"|→ {re.escape(outlets)} outlets", cell), (tier.id, cell)
        assert outlets in _svg_labels(svg), f"{svg.name}: the strip should read {outlets!r}"


def test_in_chamber_boards_get_the_6_ft_usb_cables():
    for tier, svg in zip(TIERS, TIER_SVGS):
        names = [c.name for c in tier.components]
        assert any("USB-C Data Cable, 6 ft" in n for n in names), tier.id
        labels = " | ".join(_svg_labels(svg))
        assert "6 ft (2 m)" in labels, svg.name
    power = _section(_read(GUIDE), "Power and cabling")
    assert "6 ft (2 m) USB-A → USB-C" in power and "6 ft (2 m) USB-A → micro-USB" in power


# Every cabling / consumable BOM line must have a row in the build guide's
# "Cables, connectors and consumables" table. A new line with no entry here
# fails: add its row to the guide (§7) and its key to this map.
_CABLING_ROWS = {
    "Surge Protector Power Strip": "Surge-protector power strip",
    "DC Barrel Pigtail": "DC barrel pigtail",
    "USB-A to USB-C Data Cable": "USB-A → USB-C",
    "USB-A to Micro-USB": "USB-A → micro-USB",
    "USB Wall Charger": "USB wall chargers",
    "18 AWG 2-Conductor": "18 AWG 2-conductor red/black wire",
    "22 AWG Stranded Hookup": "22 AWG stranded hookup wire",
    "22 AWG 4-Conductor": "22 AWG 4-conductor cable",
    "WAGO 221": "WAGO 221 lever connectors",
    "Inline ATC/ATO": "Inline ATC/ATO fuse holders",
    "ATC Blade Fuse Assortment": "ATC fuse assortment",
    "Noctua NA-SEC3": "Noctua NA-SEC3",
    "Adhesive-Lined Heat Shrink": "Adhesive-lined 3:1 heat-shrink",
    "UV-Resistant Zip Ties": "UV zip ties",
    "Zip Ties, 18": "18\" (457 mm) UV zip ties",
    "VELCRO ONE-WRAP": "VELCRO ONE-WRAP",
    "Rubber Grommet Kit": "Rubber grommet kit",
    "Food-Grade Silicone Tubing": "Food-grade silicone tubing",
    "Lead-Free Rosin-Core Solder": "Lead-free solder",
    "ruthex Heat-Set Insert": "Heat-set inserts + socket-head screw kits",
    "Heat-Set Inserts M2.5": "Heat-set inserts + socket-head screw kits",
    "M2.5 Socket Head Screw Kit": "Heat-set inserts + socket-head screw kits",
    "M3 x 6 mm Socket Head Screws": "Heat-set inserts + socket-head screw kits",
    "Socket Head Screw Kit M2.5-M8": "Heat-set inserts + socket-head screw kits",
    "M4 Socket Head Screw Kit": "Heat-set inserts + socket-head screw kits",
    "M4 x 8 mm Cup-Point Set Screws": "Heat-set inserts + socket-head screw kits",
}
_NOT_CABLING = ("Raspberry Pi 27W", "12V Power Supply")
_TIER_CELL = {frozenset({"bare_bones", "recommended", "all_the_things"}): "all",
              frozenset({"recommended", "all_the_things"}): "Recommended, All the Things",
              frozenset({"all_the_things"}): "All the Things"}


def test_every_cabling_bom_line_is_mapped_in_the_build_guide():
    table = _section(_read(GUIDE), "Cables, connectors and consumables")
    rows = [[cell.strip() for cell in line.split("|")[1:-1]] for line in table.splitlines()
            if line.startswith("| ") and not line.startswith("| BOM line")]
    tiers_by_row: dict[str, set[str]] = {}
    for tier in TIERS:
        for c in tier.components:
            if c.category not in ("wiring", "hardware", "power") or c.name.startswith(_NOT_CABLING):
                continue
            key = next((k for k in _CABLING_ROWS if c.name.startswith(k)), None)
            assert key, f"BOM line {c.name!r} has no row in the build guide's cabling table"
            row = next((r for r in rows if r[0].startswith(_CABLING_ROWS[key])
                        or _CABLING_ROWS[key] in r[0]), None)
            assert row, f"build guide §7 table has no {_CABLING_ROWS[key]!r} row ({c.name})"
            tiers_by_row.setdefault(row[0], set()).add(tier.id)
    for row in rows:
        want = _TIER_CELL.get(frozenset(tiers_by_row.get(row[0], ())))
        if want and row[2] in _TIER_CELL.values():
            assert row[2] == want, f"{row[0]!r}: the BOM carries it on {want!r}, the guide says {row[2]!r}"


def test_build_guide_lists_the_tools():
    tools = _section(_read(GUIDE), "Tools you need").lower()
    for tool in ("soldering iron", "heat-set insert tip", "wire strippers", "crimper", "multimeter",
                 "heat gun", "hex keys", "flush cutters", "3d printer"):
        assert tool in tools, f"Tools you need misses {tool}"


def test_tier1_climate_node_has_no_breadboard_or_jumpers():
    labels = " | ".join(_svg_labels(DOCS / "wiring-tier1-bare-bones.svg"))
    assert "Dupont" not in labels and "jumper" not in labels.lower()
    assert "no breadboard" in labels
    assert not any(c.name.startswith(("Breadboard", "Dupont")) for c in TIERS[0].components)


def test_models_readme_matches_the_model_headers():
    readme = _read(MODELS_README)
    # cam_mount: the default print plate's piece count.
    plate = re.search(r"default print plate: ([^)]*)\)", _scad_header("cam_mount.scad"))
    assert plate, "cam_mount.scad header no longer names its default print plate"
    pieces = sum(int(m.group(1) or 1) for m in
                 re.finditer(r"(?:^|\+)\s*(?:(\d+) )?[a-z]", plate.group(1)))
    row = next(line for line in readme.splitlines() if line.startswith("| [`cam_mount.scad`]"))
    assert re.search(rf"\| {pieces} \(", row), f"cam_mount prints {pieces} pieces: {row}"
    # sensor_mount: one SCD-41 height in the README and the file header.
    header_h = re.search(r"SCD-41 / 5187 SCD-40:.{0,80}?([\d.]+) mm tall",
                         _scad_header("sensor_mount.scad")).group(1)
    scd_row = next(line for line in readme.splitlines() if "SCD-41 / **5187**" in line)
    assert re.findall(r"([\d.]+) mm tall", scd_row) == [header_h], scd_row
    assert not re.search(r"mm tall \(page: [\d.]+\)", scd_row), scd_row


def test_agents_md_firmware_constraints_match_v2():
    text = _read(AGENTS)
    for stale in ("SPIFFS", "8-bit for relays", "lib/sporeprint_common", "matplotlib"):
        assert stale not in text, f"AGENTS.md still says {stale!r}"


def test_readme_drops_features_that_do_not_exist():
    text = _read(README)
    for stale in ("matplotlib", "PDF grow reports", "setup-pi.sh handles", "cd ui && npm",
                  "cp .env.example .env    # edit"):
        assert stale not in text, f"README still says {stale!r}"


_LINK = re.compile(r"\]\(([^)\s]+)\)")


@pytest.mark.parametrize("doc", CURRENT_MD, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(doc):
    missing = []
    for target in _LINK.findall(_read(doc)):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = (doc.parent / target.split("#")[0]).resolve()
        if not path.exists():
            missing.append(target)
    assert not missing, f"{doc.relative_to(ROOT)} links to missing files: {missing}"


def test_env_example_doc_references_exist():
    for ref in re.findall(r"docs/[\w./-]+\.md", _read(ROOT / ".env.example")):
        assert (ROOT / ref).exists(), f".env.example points at missing {ref}"


# ── Headline facts (2026-10 docs pass) ───────────────────────────────
# CLAUDE.md had drifted for months (no auth → opt-in bearer, SSRs, a SPIFFS
# buffer, 8-bit relay PWM, three species categories, a phase list without
# cold_storage) while nothing checked it, and README named a Socket.IO event
# the server never emits. These pin the facts every overview repeats. Since
# the 2026-10 context pass CLAUDE.md imports AGENTS.md and the spec's
# reference material lives in docs/species-reference.md and
# docs/feature-status.md, so the facts are pinned where they now live.

_CATEGORY_COUNT_DOCS = [README, SPECIES_REF]
_PWM_DOCS = [README, AGENTS]


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))
_CATEGORIES = ("gourmet", "medicinal", "active", "novelty")


def _category_counts() -> dict[str, int]:
    counts = {c: 0 for c in _CATEGORIES}
    for profile in BUILTIN_PROFILES:
        counts[profile.category] += 1
    return counts


def test_species_categories_are_the_four_the_docs_name():
    assert {p.category for p in BUILTIN_PROFILES} == set(_CATEGORIES)


@pytest.mark.parametrize("doc", _CATEGORY_COUNT_DOCS, ids=_rel)
def test_species_category_counts_match_the_code(doc):
    counts = _category_counts()
    text = _read(doc)
    claims = [(c.lower(), int(n)) for n, c in
              re.findall(r"\b(\d+) (gourmet|medicinal|active|novelty)\b", text, re.I)]
    claims += [(c.lower(), int(n)) for c, n in
               re.findall(r"\*\*(gourmet|medicinal|active|novelty)\*\* \((\d+)", text, re.I)]
    assert claims, f"{doc.name} states no per-category species count"
    wrong = [(c, n) for c, n in claims if counts[c] != n]
    assert not wrong, f"{doc.name}: {wrong} — profiles.py has {counts}"
    assert {c for c, _ in claims} == set(_CATEGORIES), f"{doc.name} misses a category count"


def test_agents_md_lists_every_grow_phase_in_order():
    m = re.search(r"GrowPhase enum: ([a-z_, ]+)", _read(AGENTS))
    assert m, "AGENTS.md no longer lists the GrowPhase enum"
    listed = [p.strip() for p in m.group(1).split(",")]
    assert listed == [p.value for p in GrowPhase], listed


def test_species_reference_grow_phase_enum_matches_the_code():
    block = re.search(r"class GrowPhase\(str, Enum\):\n((?:    .*\n)+)", _read(SPECIES_REF))
    assert block, f"{SPECIES_REF.name} has no GrowPhase block"
    listed = re.findall(r'= "([a-z_]+)"', block.group(1))
    assert listed == [p.value for p in GrowPhase], listed


def _platform() -> tuple[str, str]:
    """(pioarduino release tag, Arduino-ESP32 core version) from [esp32_base]."""
    ini = _read(PLATFORMIO_INI)
    base = re.split(r"^\[esp32_base\]$", ini, maxsplit=1, flags=re.M)[1].split("\n[", 1)[0]
    url = re.search(r"^platform = (\S+)", base, re.M).group(1)
    tag = re.search(r"/download/(\d+\.\d+\.\d+-\d+)/", url).group(1)
    _idf, major, rest = tag.split("-")[0].split(".")
    # pioarduino tags read <IDF major+minor>.<core major>.<core minor + patch>:
    # 55.03.312 = ESP-IDF 5.5, Arduino-ESP32 core 3.3.12.
    return tag, f"{int(major)}.{rest[0]}.{int(rest[1:])}"


_PLATFORM_DOCS = [README, AGENTS, FW_README, GUIDE]


@pytest.mark.parametrize("doc", [*_PLATFORM_DOCS, *_QUIET_DOCS], ids=_rel)
def test_docs_name_the_pinned_platform(doc):
    tag, core = _platform()
    text = _read(doc)
    if doc in _PLATFORM_DOCS:
        assert f"core {core}" in text, f"{doc.name} never names Arduino-ESP32 core {core}"
    for other in re.findall(r"\bcore (3\.\d+\.\d+)\b", text):
        assert other == core, f"{doc.name} names core {other}; platformio.ini pins {core}"
    for other in re.findall(r"\b(5\d\.\d\d\.\d+-\d+)\b", text):
        assert other == tag, f"{doc.name} names pioarduino {other}; platformio.ini pins {tag}"
    if doc in (README, FW_README, GUIDE):
        assert "6.2.0" in text and "git" in text, f"{doc.name}: pioarduino needs PlatformIO 6.2.0+ and git"


def test_agents_and_firmware_readme_name_the_platform_release():
    tag, _core = _platform()
    for doc in (AGENTS, FW_README):
        assert tag in _read(doc), f"{doc.name} does not name the pinned release {tag}"


def test_builder_setup_step_names_the_toolchain():
    """2026-10 audit: every tier's Builder setup said only `pip install platformio`
    (no -U, no Core version, nothing about core 3.x), so a reader with an older
    PlatformIO install hit a platform-install failure the README warns about."""
    _tag, core = _platform()
    for tier in TIERS:
        steps = [s for s in tier.setup_steps if "pip install" in s and "platformio" in s]
        assert steps, f"{tier.name}: no PlatformIO install step"
        for step in steps:
            assert "pip install -U platformio" in step, f"{tier.name}: {step}"
            assert "6.2.0" in step and "git" in step, f"{tier.name}: needs Core 6.2.0+ and git"
            assert f"core {core}" in step, f"{tier.name}: names no Arduino-ESP32 core {core}"
            assert "1 GB" in step, f"{tier.name}: the first-build download is not mentioned"


def _pwm_spec() -> tuple[int, int]:
    header = "board_profile_esp32dev.h"
    return int(_board_pin(header, "SP_LEDC_FREQ_HZ")), int(_board_pin(header, "SP_LEDC_RES_BITS"))


def test_every_node_board_shares_the_pwm_spec():
    freq, bits = _pwm_spec()
    for header in ("board_profile_esp32s3.h",):
        assert (int(_board_pin(header, "SP_LEDC_FREQ_HZ")),
                int(_board_pin(header, "SP_LEDC_RES_BITS"))) == (freq, bits), header


@pytest.mark.parametrize("doc", [*_PWM_DOCS, FW_README, FW_DRIVERS, *_QUIET_DOCS], ids=_rel)
def test_docs_state_the_pwm_spec(doc):
    freq, bits = _pwm_spec()
    pwm_lines = [line for line in _read(doc).splitlines() if re.search(r"PWM|LEDC", line)]
    if doc not in _QUIET_DOCS:
        assert any(f"{freq // 1000} kHz" in line or f"{freq // 1000}kHz" in line for line in pwm_lines), (
            f"{doc.name} never states {freq // 1000} kHz PWM")
        assert any(f"{bits}-bit" in line for line in pwm_lines), f"{doc.name} never states {bits}-bit PWM"
    for line in pwm_lines:
        for khz in re.findall(r"\b(\d+) ?kHz", line):
            assert int(khz) == freq // 1000, f"{doc.name}: {line.strip()}"
        for b in re.findall(r"\b(\d+)-bit\b", line):
            assert int(b) == bits, f"{doc.name}: {line.strip()}"


def test_offline_buffer_size_matches_the_firmware():
    src = _read(ROOT / "firmware" / "lib" / "sp_core" / "telemetry_buffer.h")
    kb = int(re.search(r"cap_bytes = (\d+) \* 1024", src).group(1))
    for doc in (AGENTS, FEATURE_STATUS):
        assert f"{kb} KB" in _read(doc), f"{doc.name} should state the {kb} KB offline buffer"
    for doc in (AGENTS, FEATURE_STATUS, *SPEC):
        assert not re.search(r"SPIFFS ring buffer|1000 entries", _read(doc)), doc.name


@pytest.mark.parametrize("doc", [FW_README], ids=_rel)
def test_firmware_overviews_list_every_env(doc):
    envs = re.findall(r"^\[env:([a-z0-9_]+)\]", _read(PLATFORMIO_INI), re.M)
    text = _read(doc)
    for env in envs:
        assert f"`{env}`" in text, f"{doc.name} never names env {env}"


def test_agents_commands_build_every_image_on_the_image_python():
    envs = re.findall(r"^\[env:([a-z0-9_]+)\]", _read(PLATFORMIO_INI), re.M)
    rows = {re.match(r"\| ([^|]+) \|", ln).group(1): ln
            for ln in _read(AGENTS).splitlines() if re.match(r"\| [A-Z][^|]* \| `", ln)}
    built = re.findall(r"-e (\w+)", rows["Firmware images"])
    assert sorted(built) == sorted(e for e in envs if e != "native"), built
    assert "-e native" in rows["Firmware host tests"]
    image = re.search(r"^FROM python:(\d+\.\d+)", _read(ROOT / "server" / "Dockerfile"), re.M).group(1)
    assert f"uv sync --python {image} --extra dev" in rows["Server lint + tests"], (
        "AGENTS' server command should pin the Docker image's Python")


def _local_socket_events() -> set[str]:
    """Events the Pi's own Socket.IO server emits (app/cloud/ talks to the
    cloud relay as a client — its command_result acks are not local)."""
    events = set()
    for path in (ROOT / "server" / "app").rglob("*.py"):
        if "cloud" in path.relative_to(ROOT / "server" / "app").parts:
            continue
        events.update(re.findall(r"\bsio\.emit\(\s*\"(\w+)\"", _read(path)))
    return events


def test_readme_socket_events_are_the_ones_the_server_emits():
    table = _section(_read(README), "WebSocket Events")
    listed = set(re.findall(r"^\| `(\w+)` \| Server -> Client", table, re.M))
    assert listed == _local_socket_events(), (
        f"README lists {sorted(listed)}; the server emits {sorted(_local_socket_events())}")


@pytest.mark.parametrize("doc", [README, GUIDE, SMART_PLUGS, BROKER_README], ids=_rel)
def test_shelly_gen2_prefix_is_documented(doc):
    acl = _read(ROOT / "config" / "mosquitto" / "acl.conf")
    assert "topic write shellies/+/rpc" in acl, "the server's Gen2 command grant moved"
    text = _read(doc)
    assert "shellies/<role>" in text, f"{doc.name} never gives the Gen2 MQTT prefix"
    if doc is not BROKER_README:
        assert "RPC status notifications over MQTT" in text, doc.name


def test_readme_mqtt_topics_cover_every_node_topic_the_acl_grants():
    topics = _section(_read(README), "MQTT Topics")
    acl = _read(ROOT / "config" / "mosquitto" / "acl.conf")
    for kind in re.findall(r"^pattern (?:readwrite|write) sporeprint/%u/([a-z]+)", acl, re.M):
        assert f"sporeprint/{{node_id}}/{kind}" in topics, f"README MQTT Topics misses {kind}"
    for cmd in ("cmd/coredump_ack", "cmd/ota_manifest"):
        assert f"sporeprint/{{node_id}}/{cmd}" in topics, f"README MQTT Topics misses {cmd}"


@pytest.mark.parametrize("doc", [AGENTS, FEATURE_STATUS, *SPEC], ids=_rel)
def test_agent_context_states_the_auth_model(doc):
    # The spec said "No authentication layer" long after v3.3.0 added the
    # opt-in bearer gate. AGENTS.md (which CLAUDE.md imports) carries the model.
    text = _read(doc)
    if doc is AGENTS:
        assert "ApiKeyMiddleware" in text and "SPOREPRINT_API_KEY" in text
        assert "SPOREPRINT_ALLOW_UNAUTHENTICATED" in text
    assert "**No authentication layer**" not in text
    for stale in ("IRLZ44N SSRs", "lib/sporeprint_common/` —", "8-bit (0–255)"):
        assert stale not in text, f"{doc.name} still says {stale!r}"


# ── 2026-10 docs audit, round 1: claims pinned to the code ──────────


def test_readme_names_the_screen_that_makes_the_pairing_code():
    # The code is generated in Setup → § III Cloud link; Settings has only a
    # static "Cloud pairing" row with no button.
    text = _read(README)
    assert "Setup → § III Cloud link" in text
    for doc in CURRENT_MD:
        assert "Settings → Cloud Pairing" not in _read(doc), doc.name


def test_no_doc_says_unknown_env_keys_stop_the_server():
    assert Settings.model_config.get("extra") == "ignore"
    for doc in CURRENT_MD:
        assert not re.search(r"refuses to start on a non-empty key", _read(doc)), doc.name


def test_agents_states_the_frame_liveness_rule_the_code_applies():
    line = next(ln for ln in _read(AGENTS).splitlines() if ln.startswith("- Telemetry timestamps"))
    # Liveness is replay / out-of-order against the node's newest ts — never
    # a frame's age against the Pi clock ("synced frames older than 120 s").
    assert "older than 120 s are stored" not in line
    assert '"replay": true' in line and "out-of-order" in line, line
    assert f"{_CLOCK_STEP_BACK_SECONDS} s" in line and "re-baselines" in line, line


def test_no_doc_says_the_supported_s3_camera_boards_are_unsupported():
    ini = _read(PLATFORMIO_INI)
    assert re.search(r"^\[env:cam_waveshare_s3\]", ini, re.M)
    for doc in CURRENT_MD:
        text = _read(doc)
        assert not re.search(r"\"ESP32-S3-CAM\" boards are\s+\*\*not\*\*\s+supported", text), doc.name
    guide = _read(GUIDE)
    assert "Waveshare ESP32-S3-CAM" in guide and "§8b" in guide


def test_readme_feature_list_claims_only_what_exists():
    text = _read(README)
    # A/B: the comparison returns per-metric values, no telemetry series
    assert "Side-by-side telemetry" not in text
    # chambers: /api/chambers/compare exists, a dashboard view does not
    assert "**Comparison view**" not in text
    assert "GET /api/chambers/compare" in text
    # notifications: one ntfy topic for every tier
    assert "Configurable topics" not in text
    assert "one ntfy topic" in text


def test_readme_label_claims_match_the_labels_router():
    text = _read(README)
    assert not re.search(r"Phomemo|NIIMBOT|Thermal printer support", text)
    row = next(l for l in text.splitlines() if l.startswith("| `labels` |"))
    named = set(re.findall(r"\b(session|culture|container)s?\b", row))
    assert named == set(_LABEL_PATHS), row


def _api_operations_by_prefix() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path, item in server_app.openapi()["paths"].items():
        seg = path.split("/")
        key = seg[2] if seg[1] == "api" else seg[1]
        ops = [m for m in item if m in ("get", "post", "put", "patch", "delete")]
        counts[key] = counts.get(key, 0) + len(ops)
    return counts


def test_readme_server_modules_table_lists_the_packages():
    app_dir = ROOT / "server" / "app"
    packages = sorted(p.parent.name for p in app_dir.glob("*/__init__.py"))
    section = _section(_read(README), "Server Modules")
    rows = re.findall(r"^\| `([a-z_]+)(?:\.py)?` [^|]*\| (\d+)", section, re.M)
    listed = {name: int(n) for name, n in rows}
    module_rows = [n for n, _ in rows if n in packages]
    assert sorted(module_rows) == packages, "every server/app package, once"
    assert f"The {len(packages)} packages" in section
    assert f"**{len(packages)} server modules**" in _read(README)
    ops = _api_operations_by_prefix()
    for name, n in listed.items():
        key = name.removesuffix("_router")
        assert ops.get(key, 0) == n, f"{name}: README says {n}, the API has {ops.get(key, 0)}"
    # the single-file routers are labelled as files, not modules
    for single in ("settings_router.py", "provision.py"):
        assert (app_dir / single).exists()
        assert f"`{single}`" in section


def test_agents_module_pattern_claim_matches_the_files():
    line = next(ln for ln in _read(AGENTS).splitlines() if ln.startswith("- Package layout"))
    app_dir = ROOT / "server" / "app"
    layers = ("models.py", "service.py", "router.py")
    claims = {  # sentence of the line -> the layer files those packages have
        "have all three": set(layers),
        "is router-only": {"router.py"},
        "are service-only": {"service.py"},
    }
    named = set()
    for clause in line.split(";"):
        for phrase, want in claims.items():
            if phrase in clause:
                for mod in re.findall(r"\b([a-z]+)/", clause):
                    have = {f for f in layers if (app_dir / mod / f).exists()}
                    assert have == want, f"AGENTS says {mod}/ has {sorted(want)}, it has {sorted(have)}"
                    named.add(mod)
    assert {"labels", "notifications", "retention", "sessions"} <= named, line
    packages = {p.parent.name for p in app_dir.glob("*/__init__.py")}
    three = {p for p in packages if all((app_dir / p / f).exists() for f in layers)}
    assert three <= named, f"AGENTS' package-layout line misses {sorted(three - named)}"


# docs/species-reference.md tables the gourmet and medicinal species whose
# automation is special; the operator's CLAUDE.md keeps the active ones
# (public docs name no active species). Both say their tables give
# profiles.py's values, so every parseable cell is checked against the code.
_SPECIES_TABLES = {
    SPECIES_REF: {
        "Blue Oyster": "blue_oyster",
        "Pink Oyster": "pink_oyster",
        "King Trumpet": "king_trumpet",
        "Lion's Mane": "lions_mane",
        "Shiitake": "shiitake",
        "Reishi": "reishi",
        "Cordyceps militaris": "cordyceps_militaris",
        "Turkey Tail": "turkey_tail",
    },
    CLAUDE: {
        "Cubensis — Golden Teacher": "cubensis_golden_teacher",
        "Cubensis — Penis Envy (PE)": "cubensis_penis_envy",
    },
}
_TABLE_PHASES = {
    "agar": "agar", "liquid culture": "liquid_culture", "grain colonization": "grain_colonization",
    "substrate colonization": "substrate_colonization", "browning/popcorning": "browning",
    "primordia induction": "primordia_induction", "fruiting": "fruiting", "rest": "rest",
}
_FAE_MODES = ("none", "passive", "scheduled", "continuous")
_RANGE = re.compile(r"^(\d+)–(\d+)")


def _species_rows(doc: Path):
    """(where, cells, PhaseParams) for every row of the doc's species tables."""
    text = _read(doc)
    profiles = {p.id: p for p in BUILTIN_PROFILES}
    for heading, pid in _SPECIES_TABLES[doc].items():
        m = re.search(rf"^#+ {re.escape(heading)}[^\n]*\n", text, re.M)
        assert m, f"{doc.name} has no {heading!r} section"
        table = re.search(r"^\| Phase [^\n]*\n\|[-| ]+\n((?:\|[^\n]*\n)+)", text[m.end():], re.M)
        assert table, f"{doc.name}: {heading} has no table"
        for row in table.group(1).splitlines():
            cells = [c.strip().replace("*", "") for c in row.strip("|").split("|")]
            label = cells[0]
            enum = re.search(r"`([a-z_]+)`", label)
            key = enum.group(1) if enum else _TABLE_PHASES[re.sub(r"\s*\(.*\)$", "", label).lower()]
            yield f"{doc.name} · {heading} · {label}", cells, profiles[pid].phases[key]


def _ints(m: re.Match) -> tuple[int, ...]:
    return tuple(int(g) for g in m.groups())


@pytest.mark.parametrize("doc", [SPECIES_REF, *SPEC], ids=_rel)
def test_species_tables_give_the_profiles_values(doc):
    rows = 0
    for where, cells, p in _species_rows(doc):
        rows += 1
        _label, temp, rh, co2, light, fae, days = cells
        assert _ints(_RANGE.match(temp)) == (int(p.temp_min_f), int(p.temp_max_f)), (where, temp)
        if m := _RANGE.match(rh):
            assert _ints(m) == (int(p.humidity_min), int(p.humidity_max)), (where, rh)
        if m := re.match(r"≤ (\d+)", co2):
            assert int(m.group(1)) == p.co2_max_ppm and not p.co2_min_ppm, (where, co2)
        else:
            assert _ints(_RANGE.match(co2)) == (p.co2_min_ppm, p.co2_max_ppm), (where, co2)
        if light.startswith("dark"):
            assert p.light_hours_on == 0, (where, light)
        else:
            hours = re.search(r"\b(\d+)/(\d+)\b", light)
            assert hours and _ints(hours) == (p.light_hours_on, p.light_hours_off), (where, light)
        if m := re.search(r"(\d+) lux", light):
            assert int(m.group(1)) == p.light_lux_target, (where, light)
        mode = re.match(r"[a-z]+", fae)
        assert mode and mode.group(0) in _FAE_MODES, f"{where}: name the FAE mode first ({fae!r})"
        assert mode.group(0) == p.fae_mode, f"{where}: the table says {fae!r}, the profile has {p.fae_mode!r}"
        if m := re.match(r"scheduled (\d+) min every (\d+)", fae):
            assert (int(m.group(1)) * 60, int(m.group(2))) == (p.fae_duration_sec, p.fae_interval_min), where
        if m := _RANGE.match(days):
            assert _ints(m) == tuple(p.expected_duration_days), (where, days)
    assert rows >= 2 * len(_SPECIES_TABLES[doc]), doc.name


# docs/automation-rules.md tables every built-in rule. An unlisted, renamed
# or re-prioritised built-in, or a scope that drifts, fails here.
_RULE_SCOPE_PHASES = {
    "open": ("browning", "primordia_induction", "fruiting"),
    "primordia": ("primordia_induction",), "fruiting": ("fruiting",),
    "substrate": ("substrate_colonization",), "grain": ("grain_colonization",),
}


def _builtin_rule_rows() -> dict[str, list[str]]:
    table = _section(_read(AUTOMATION_RULES), "Built-in rules")
    rows = {}
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| ") and len(cells) == 5 and cells[1].isdigit():
            rows[cells[0]] = cells
    return rows


def test_automation_rules_doc_lists_every_builtin():
    rows = _builtin_rule_rows()
    assert set(rows) == {r.name for r in BUILTIN_RULES}, (
        sorted(set(rows) ^ {r.name for r in BUILTIN_RULES}))
    text = _read(AUTOMATION_RULES)
    assert f"seeds {len(BUILTIN_RULES)} built-in rules" in text
    for rule in BUILTIN_RULES:
        name, priority, scope, _when, _does = rows[rule.name]
        assert int(priority) == rule.priority, (name, priority, rule.priority)
        species = re.findall(r"`([a-z_]+)`", scope)
        assert species == (rule.applies_to_species or []), (name, scope)
        words = [w.strip() for w in re.sub(r"`[a-z_]+`", "", scope).split(",") if w.strip()]
        phases = sorted(p for w in words if w != "all" for p in _RULE_SCOPE_PHASES[w])
        assert phases == sorted(rule.applies_to_phases or []), (name, scope)
        assert ("all" in words) == (rule.applies_to_phases is None), (name, scope)


def test_automation_rules_doc_names_every_superseded_table():
    """The upgrade path for a changed built-in stays documented where agents
    look: the tables _superseded_builtin_rules folds exist under the names
    the page and AGENTS.md use."""
    folded = re.findall(r"\b([A-Z_]+_BUILTIN_RULES)\b",
                        inspect.getsource(rule_templates._superseded_builtin_rules))
    assert folded, "no superseded tables found"
    text, agents = _read(AUTOMATION_RULES), _read(AGENTS)
    for name in (*folded, "SUPERSEDED_BUILTIN_RULES"):
        assert hasattr(rule_templates, name), name
    assert "LEGACY_BUILTIN_RULES" in text and "PRE_<change>_BUILTIN_RULES" in text
    assert "SUPERSEDED_BUILTIN_RULES" in text and "SUPERSEDED_BUILTIN_RULES" in agents
    assert "docs/automation-rules.md#changing-a-built-in-rule" in agents


_STATUSES = ("Not built", "Partial", "Not needed")


def test_feature_status_rows_use_the_legend():
    text = _read(FEATURE_STATUS)
    for status in _STATUSES:
        assert f"**{status}**" in text, f"the legend does not define {status!r}"
    rows = [ln for ln in text.splitlines()
            if ln.startswith("| ") and not ln.startswith(("| Spec item", "| Spec section"))]
    statuses = [ln.strip("|").split("|")[1].strip() for ln in rows if ln.count("|") == 4]
    assert statuses, "no feature rows parsed"
    assert set(statuses) <= set(_STATUSES), sorted(set(statuses) - set(_STATUSES))


def test_docs_describe_watchdog_and_vision_as_built():
    for doc in (AGENTS, FEATURE_STATUS, *SPEC):
        assert "restored when MQTT returns" not in _read(doc), doc.name
    assert "reported as `safety_cutoff`" in _read(AGENTS)
    vision = next(ln for ln in _read(FEATURE_STATUS).splitlines() if ln.startswith("| Vision page"))
    assert "confirm/correct UI" not in vision
    assert "manual contamination mark" in vision


# ── 2026-10 browser audit, round 2 ───────────────────────────────────
# README claims the dashboard did not back up: a drying tracker and report
# downloads on Sessions (the page links only a finished session's report.md),
# QR labels "for thermal printers" (the API returns a PNG), and a "6-step"
# wizard (the dashboard asks five questions; the API scores six inputs).


def _ui_pages_row(page: str) -> str:
    table = _section(_read(README), "UI Pages")
    row = next((line for line in table.splitlines() if line.startswith(f"| {page} |")), None)
    assert row, f"README UI Pages has no {page!r} row"
    return row


def test_readme_sessions_page_row_names_only_what_the_page_has():
    row = _ui_pages_row("Sessions")
    for stale in ("drying tracker", "report downloads"):
        assert stale not in row, f"README UI Pages says Sessions has a {stale}"
    assert "report.md" in row
    assert "API-only" in row  # the drying log and report.csv stay API routes
    paths = server_app.openapi()["paths"]
    assert "/api/sessions/{session_id}/report.csv" in paths
    assert any(p.endswith("/drying") or p.endswith("/drying-log") for p in paths)


def test_readme_labels_are_png_qr_codes_not_printer_support():
    text = _read(README)
    assert "thermal printer" not in text
    tree_line = next(line for line in text.splitlines() if "── labels/" in line)
    assert "QR code PNGs" in tree_line
    assert set(_LABEL_PATHS) >= {"session", "culture"}


def test_readme_wizard_counts_match_the_scorer():
    # include_active filters the candidate pool; it is not a scored input.
    inputs = [n for n, prm in inspect.signature(recommend).parameters.items()
              if prm.kind is inspect.Parameter.KEYWORD_ONLY and n not in ("limit", "include_active")]
    assert len(inputs) == 6
    line = next(row for row in _read(README).splitlines() if "**Species Selector Wizard**" in row)
    assert "6-step" not in line
    assert "five-question" in line and "six inputs" in line


# ── 2026-10 release docs pass ────────────────────────────────────────
# The architecture diagram still drew a React 18 PWA on Zustand + Socket.IO,
# cloud-relay-flow.md a command shape (`target`) and OTA step names the code
# never used, README a 32-character cloud channel, dual-repo-architecture.md
# a Mermaid block that did not parse, and the build guide had no pin table
# for the camera boards. These pin each to the code.


def _defines(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2).split("//")[0].strip()
            for m in re.finditer(r"^#define (SP_\w+) (.+)$", text, re.M)}


def _camera_profiles() -> dict[str, dict[str, str]]:
    """Each camera env's board defines, from firmware/boards/."""
    boards = ROOT / "firmware" / "boards"
    s3 = _read(boards / "board_profile_esp32s3cam.h")
    xiao = s3.split("#if defined(SP_CAM_BOARD_XIAO_S3)", 1)[1].split("#elif", 1)[0]
    waveshare = s3.split("#elif defined(SP_CAM_BOARD_WAVESHARE_S3)", 1)[1].split("#else", 1)[0]
    freenove = s3.split("#else  // SP_CAM_BOARD_S3_EYE", 1)[1].split("#endif", 1)[0]
    shared = _defines(s3.split("#endif", 1)[1])
    ai_thinker = _defines(_read(boards / "board_profile_esp32cam.h"))
    default_hz = re.search(r"#define SP_CAM_XCLK_HZ (\d+)",
                           _read(ROOT / "firmware" / "src" / "cam" / "main.cpp")).group(1)
    ai_thinker.setdefault("SP_CAM_XCLK_HZ", default_hz)
    return {"cam": ai_thinker, "cam_esp32s3": {**_defines(freenove), **shared},
            "cam_xiao_esp32s3": {**_defines(xiao), **shared},
            "cam_waveshare_s3": {**_defines(waveshare), **shared}}


def _y_pins(d: dict[str, str]) -> list[str]:
    return [d[f"SP_CAM_Y{i}"] for i in range(2, 10)]


def test_build_guide_camera_pin_table_matches_the_board_headers():
    section = _section(_read(GUIDE), "ESP32-S3 camera boards")
    rows = [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in section.splitlines() if line.startswith("| ")]
    header = next(r for r in rows if r[0] == "Signal")
    envs = [re.search(r"`(\w+)`", cell).group(1) for cell in header[1:]]
    profiles = _camera_profiles()
    assert set(envs) == set(profiles), envs
    table = {r[0]: dict(zip(envs, r[1:])) for r in rows if r[0] != "Signal"}

    def row(label: str) -> dict[str, str]:
        return next(v for k, v in table.items() if k.startswith(label))

    for env, d in profiles.items():
        mhz = int(d["SP_CAM_XCLK_HZ"]) // 1_000_000
        assert row("XCLK")[env].startswith(f"GPIO {d['SP_CAM_XCLK']}, {mhz} MHz"), env
        assert row("SCCB")[env].startswith(f"GPIO {d['SP_CAM_SIOD']} / {d['SP_CAM_SIOC']}"), env
        assert row("D0–D7")[env] == ", ".join(_y_pins(d)), env
        assert row("VSYNC")[env] == (
            f"GPIO {d['SP_CAM_VSYNC']} / {d['SP_CAM_HREF']} / {d['SP_CAM_PCLK']}"), env
        pwdn = row("Sensor power-down")[env]
        assert (f"GPIO {d['SP_CAM_PWDN']}" == pwdn) if d["SP_CAM_PWDN"] != "-1" else "GPIO" not in pwdn
        flash = row("Flash LED")[env]
        assert flash == (f"GPIO {d['SP_PIN_FLASH']}" if d["SP_PIN_FLASH"] != "-1" else "none"), env
        assert f"GPIO {d['SP_PIN_FACTORY_RESET']}" in row("Setup portal")[env], env
        assert row("Heartbeat")[env] == f"`{d['SP_BOARD_NAME'].strip(chr(34))}`", env


def test_drivers_md_camera_pin_maps_match_the_board_header():
    table = _section(_read(FW_DRIVERS), "ESP32-S3 camera boards")
    for env, d in _camera_profiles().items():
        if env == "cam":
            continue
        line = next(l for l in table.splitlines() if l.startswith(f"| `{env}` |"))
        want = (f"XCLK {d['SP_CAM_XCLK']}, SIOD {d['SP_CAM_SIOD']}, SIOC {d['SP_CAM_SIOC']}, "
                f"Y2–Y9 = {' / '.join(_y_pins(d))}, VSYNC {d['SP_CAM_VSYNC']}, "
                f"HREF {d['SP_CAM_HREF']}, PCLK {d['SP_CAM_PCLK']}")
        assert want in line, (env, line)


def test_architecture_overview_draws_the_current_stack():
    labels = " | ".join(_svg_labels(DOCS / "architecture-overview.svg"))
    for stale in ("React 18", "Zustand", "Socket.IO real-time", "REST + Socket.IO", "Alt: SCD30"):
        assert stale not in labels, stale
    assert "React 19" in labels and "not a PWA" in labels
    assert "OV5640" in labels and "Shelly Gen2+" in labels and "25 kHz 10-bit" in labels
    lowered = labels.lower()
    packages = sorted(p.parent.name for p in (ROOT / "server" / "app").glob("*/__init__.py"))
    missing = [p for p in packages if p[:6] not in lowered]
    assert not missing, f"architecture-overview.svg names no box for {missing}"


def test_readme_version_line_is_the_one_bump_sh_rewrites():
    version = re.search(r'^version = "([^"]+)"', _read(ROOT / "server" / "pyproject.toml"), re.M).group(1)
    assert re.findall(r"^\*\*Version:\*\* (\S+)$", _read(README), re.M) == [version]


def test_cloud_command_docs_match_the_pi_gate():
    from app.cloud.service import _SAFE_ID_RE, _VALID_TARGET_KINDS

    flow = _read(DOCS / "cloud-relay-flow.md")
    cloud = _section(_read(README), "Cloud Connector")
    for text, name in ((flow, "cloud-relay-flow.md"), (cloud, "README Cloud Connector")):
        assert _SAFE_ID_RE.pattern in text, f"{name} misses the channel pattern {_SAFE_ID_RE.pattern}"
        assert "{1,32}" not in text, name
        for kind in _VALID_TARGET_KINDS:
            assert f"`{kind}`" in text, f"{name} misses target_kind {kind}"
    assert "{ device_id, target_kind, channel, payload, id }" in flow
    steps = set(re.findall(r'_emit_step\(\s*"(\w+)"', _read(ROOT / "server" / "app" / "cloud" / "ota.py")))
    assert steps and all(step in flow for step in steps), steps
    for stale in ('"verifying"', '"promoting"', '"healthy"'):
        assert stale not in flow, stale


_MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)
_FLOW_STATEMENT = re.compile(
    r"^\s*(%%|subgraph\b|end\b|direction\b|classDef\b|class\b|style\b|linkStyle\b|flowchart\b|graph\b)"
    r"|\[|-->|---|-\.-|==>")
_MERMAID_DOCS = [d for d in (README, *sorted(DOCS.rglob("*.md"))) if "```mermaid" in _read(d)]


@pytest.mark.parametrize("doc", _MERMAID_DOCS, ids=_rel)
def test_mermaid_flowcharts_have_no_bare_text_lines(doc):
    # A bare line inside a flowchart is not a node, edge or directive, and
    # the whole diagram fails to render (dual-repo-architecture.md's
    # "Supabase · Railway · …" services line did, until 2026-10).
    for block in _MERMAID.findall(_read(doc)):
        if not block.lstrip().startswith(("flowchart", "graph")):
            continue
        bad = [line for line in block.splitlines() if line.strip() and not _FLOW_STATEMENT.search(line)]
        assert not bad, f"{doc.name}: {bad}"


def test_data_flow_states_the_retention_tiers():
    from app.retention import service as retention

    text = re.sub(r"\s+", " ", _read(DOCS / "data-flow.md"))
    for days in (retention.RAW_RETENTION_DAYS, retention.FIVEMIN_RETENTION_DAYS,
                 retention.FIRINGS_RETENTION_DAYS):
        assert f"{days} days" in text, days
    assert retention.HOURLY_RETENTION_DAYS == 365 and "older than a year" in text


def test_grafana_doc_lists_every_exported_metric():
    src = _read(ROOT / "server" / "app" / "integrations" / "grafana" / "exporter.py")
    text = _read(DOCS / "integrations" / "grafana" / "README.md")
    for name in set(re.findall(r'"(sporeprint_[a-z_]+)"', src)):
        shown = f"{name}_info" if name == "sporeprint_build" else name  # an Info metric
        assert f"`{shown}`" in text, f"grafana/README.md misses {shown}"


def test_smart_plug_doc_lists_every_vendor_write_action():
    from app.integrations._actions import VENDOR_ACTIONS

    table = _section(_read(SMART_PLUGS), "Write actions across the rest of the grid")
    for slug, actions in VENDOR_ACTIONS.items():
        row = next((l for l in table.splitlines() if l.lower().startswith(f"| {slug} ")), None)
        assert row, f"smart-plugs.md has no {slug} row"
        for action in actions:
            assert f"`{action}`" in row, (slug, action)



# ── 2026-10 docs audit, fix round 1 ──────────────────────────────────
# Integration docs said vendor readings drive the rules and alerts (only
# MQTT telemetry does); the public docs and the overall-system SVG showed a
# shipping iOS/Android app with a `guardWriteAction` that exists in no code;
# the cloud docs put FastAPI on :9000 (it is :9001); README promised a
# read-only free cloud path, QR labels that open the session, a
# bare-metal-only OTA key and wss:// cloud URLs; AGENTS.md implied CI and
# omitted the anchors bump.sh rewrites; the operator CLAUDE.md in the main
# checkout was still the April spec.

_INTEGRATION_READING_DOCS = [DOCS / "integrations" / "aranet" / "README.md",
                             DOCS / "integrations" / "pulse" / "README.md",
                             DOCS / "integrations" / "lighting-hvac-skeletons.md"]


def test_vendor_readings_never_reach_the_rules_and_the_docs_say_so():
    app_dir = ROOT / "server" / "app"
    callers = sorted(str(p.relative_to(app_dir)) for p in app_dir.rglob("*.py")
                     if re.search(r"await evaluate_rules\(", _read(p)))
    assert callers == ["mqtt.py"], f"evaluate_rules has new callers {callers}: update the integration docs"
    for pkg in ("integrations", "telemetry"):
        for path in (app_dir / pkg).rglob("*.py"):
            assert not re.search(r"automation\.engine|automation import engine", _read(path)), path
    for doc in _INTEGRATION_READING_DOCS:
        text = re.sub(r"\s+", " ", _read(doc))
        assert "do **not** drive automation rules" in text, doc.name
        for stale in ("continue to work", "all see Aranet readings",
                      "automation, and the Grafana exporter all work", "as if they were native sensors"):
            assert stale not in text, (doc.name, stale)


@pytest.mark.parametrize("doc", [README, *sorted(DOCS.rglob("*.md")), *SVGS], ids=_rel)
def test_docs_present_no_shipping_mobile_app(doc):
    # The Capacitor app is gone and the React Native rebuild is unreleased.
    text = _read(doc)
    for stale in ("guardWriteAction", "Mobile App (Remote)", "iOS / Android", "companion mobile app",
                  "Push (FCM)", "Native FCM (mobile)", "free = read-only", "for mobile app",
                  "The mobile app talks to"):
        assert stale not in text, f"{doc.name} still says {stale!r}"


@pytest.mark.parametrize("doc", [DOCS / "cloud-relay-flow.md", DUAL_REPO], ids=_rel)
def test_cloud_docs_put_fastapi_on_9001(doc):
    # The cloud's FastAPI listens on internal 127.0.0.1:9001; the web app
    # serves the public port.
    text = _read(doc)
    assert "127.0.0.1:9001" in text, doc.name
    assert "127.0.0.1:9000" not in text and "internal :9000" not in text, doc.name


def test_dual_repo_doc_pins_the_submodule_by_gitlink():
    text = _read(DUAL_REPO)
    assert "SHA via `.gitmodules`" not in text
    assert "submodule gitlink" in text


def test_readme_qr_labels_open_the_list_pages():
    text = _section(_read(README), "QR Code Labels")
    assert _LABEL_PATHS == {"session": "/sessions", "culture": "/cultures"}, _LABEL_PATHS
    assert "Sessions page" in text and "Cultures page" in text
    assert "open the session in" not in text


def _config_row(name: str) -> str:
    return next(ln for ln in _read(README).splitlines() if ln.startswith(f"| `{name}`"))


def test_readme_ota_key_row_covers_signed_node_manifests():
    row = _config_row("SPOREPRINT_OTA_PUBKEY_B64")
    assert "bare-metal installs only" not in row
    assert "signed node-firmware manifests" in row and "Settings → OTA verify key" in row
    assert "SPOREPRINT_OTA_PUBKEY_B64" in _read(ROOT / "docker-compose.yml")
    assert "_load_pinned_pubkey" in _read(ROOT / "server" / "app" / "hardware" / "node_manifest.py")


def test_readme_cloud_url_row_matches_the_transport_check():
    from app.cloud.service import cloud_url_transport_ok

    assert cloud_url_transport_ok("https://sporeprint.ai")
    assert cloud_url_transport_ok("http://192.168.1.20:9001")
    assert not cloud_url_transport_ok("http://example.com")
    row = _config_row("SPOREPRINT_CLOUD_URL")
    assert "`wss://` only" not in row
    assert "plain `http://` only to a LAN/loopback dev relay" in row


def test_readme_cloud_connector_says_remote_control_is_premium_only():
    text = _section(_read(README), "Cloud Connector")
    assert "premium only" in text and "free = read-only" not in text
    assert "Remote control requires premium tier" in _read(ROOT / "server" / "app" / "cloud" / "service.py")


def test_agents_says_no_ci_runs_on_push_and_none_does():
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        on = re.search(r"^on:\s*\n((?:[ \t]+[^\n]*\n|[ \t]*\n)*)", _read(wf), re.M).group(1)
        assert "pull_request" not in on, wf.name
        if re.search(r"^\s+push:", on, re.M):
            assert "tags:" in on and "branches" not in on, wf.name
    text = _read(AGENTS)
    assert "**No CI runs on push or PR**" in text
    assert "CI runs `--check`" not in text


def test_agents_names_the_version_anchors_bump_rewrites():
    version = re.search(r'^version = "([\d.]+)"', _read(ROOT / "server" / "pyproject.toml"), re.M).group(1)
    line = next(ln for ln in _read(AGENTS).splitlines() if "Never hand-edit the strings it rewrites" in ln)
    for rel in ("server/app/main.py", "server/pyproject.toml", "server/tests/test_api.py", "firmware/VERSION.txt"):
        assert f"`{rel}`" in line, rel
        assert version in _read(ROOT / rel), f"{rel} no longer carries {version}"
    assert "`**Version:**`" in line and f"**Version:** {version}" in _read(README)


def test_agents_states_the_cors_rule_the_code_keeps():
    main = _read(ROOT / "server" / "app" / "main.py")
    assert "allow_origin_regex=_LAN_ORIGIN_REGEX" in main and "allow_origins=" not in main
    assert "sporeprint.ai" not in re.search(r"_LAN_ORIGIN_REGEX = \((.*?)\n\)", main, re.S).group(1)
    text = _read(AGENTS)
    assert "`_LAN_ORIGIN_REGEX`" in text and 'never `allow_origins=["*"]`' in text


@pytest.mark.parametrize("doc", SPEC, ids=_rel)
def test_operator_claude_md_is_the_current_context_file(doc):
    # Git-ignored, so a merge never carries it: the main checkout kept the
    # 631-line April spec while worktrees had the rewrite.
    assert re.search(r"^@AGENTS\.md\s*$", _read(doc), re.M), (
        "CLAUDE.md is the pre-2026-10 spec: copy the current operator CLAUDE.md "
        "(it imports @AGENTS.md) over it")


def _env_partition_tables() -> dict[str, str]:
    """Each PlatformIO env → the partition table it builds with (via `extends`)."""
    sections: dict[str, dict[str, str]] = {}
    current = None
    for line in _read(PLATFORMIO_INI).splitlines():
        if m := re.match(r"^\[(.+)\]\s*$", line):
            current = m.group(1)
            sections[current] = {}
        elif current and (m := re.match(r"^(extends|board_build\.partitions)\s*=\s*(\S+)", line)):
            sections[current][m.group(1)] = m.group(2)

    def table(name: str) -> str | None:
        sec = sections[name]
        if "board_build.partitions" in sec:
            return sec["board_build.partitions"]
        return table(sec["extends"]) if "extends" in sec else None

    return {n.removeprefix("env:"): t for n in sections if n.startswith("env:") and (t := table(n))}


def test_partition_tables_name_the_envs_that_build_with_them():
    # partitions.csv said "shared by all four ESP32 nodes" after the nodes
    # merged into one image; partitions_8mb.csv named only the node build
    # while three S3 camera envs used it too.
    users: dict[str, set[str]] = {}
    for env, table in _env_partition_tables().items():
        users.setdefault(table, set()).add(env)
    assert set(users) == {"partitions.csv", "partitions_8mb.csv", "partitions_32mb.csv"}, users
    for table, envs in users.items():
        header = "\n".join(ln for ln in _read(ROOT / "firmware" / table).splitlines() if ln.startswith("#"))
        named = set(re.findall(r"\b(node_esp32\w*|cam(?:_\w+)?)\b", header))
        assert named == envs, f"{table} names {sorted(named)}; platformio.ini builds {sorted(envs)} with it"
    assert "all four" not in _read(ROOT / "firmware" / "partitions.csv")
    # The core the 32 MB table was laid out under is history, not the pin.
    assert "The pinned core (arduino-esp32 2.0.17" not in _read(ROOT / "firmware" / "partitions_32mb.csv")


def test_readme_chamber_rows_claim_only_what_the_pages_do():
    # The Chambers page loads chamber readings and events once (only the Pi
    # system panel polls); the inventory page cannot create chambers or
    # assign nodes; a chamber has no targets of its own.
    chambers = _ui_pages_row("Chambers (dashboard, `/`)")
    assert "live readings" not in chambers and "live event feed" not in chambers
    assert "reload to refresh" in chambers and "polled every 15 s" in chambers
    inventory = _ui_pages_row("Chamber inventory (`/inventory`)")
    assert "management and node assignment" not in inventory and "API-only" in inventory
    multi = _section(_read(README), "Multi-Chamber Management")
    assert "independent environment targets" not in multi
    assert "active grow's species profile" in multi and "neither dashboard edits chambers yet" in multi
    for model in (ChamberCreate, ChamberUpdate):
        assert not [f for f in model.model_fields if re.search(r"temp|humid|co2|target", f)], model.__name__
    assert "node_ids" in ChamberUpdate.model_fields


def test_readme_dashboard_rebuild_runs_the_generator_in_the_server_env():
    # port_builder imports app.builder.*; a bare python3 lacks pydantic/fastapi.
    text = _read(README)
    assert "python3 scripts/port_builder.py" not in text
    assert "uv run --no-sync python <monorepo>/scripts/port_builder.py --public-repo" in text


def test_agrowtek_doc_says_where_its_readings_go():
    driver = _read(ROOT / "server" / "app" / "integrations" / "agrowtek" / "driver.py")
    poll = driver[driver.index("async def poll_once"):]
    poll = poll[: poll.index("\n    async def ", 1)]
    assert "sensor_mappings" not in poll, "the driver now uses sensor_mappings: update the Agrowtek notes"
    assert 'f"agrowtek:{sensor_id}"' in poll and "store_reading(" in poll
    text = re.sub(r"\s+", " ", _read(DOCS / "integrations" / "lighting-hvac-skeletons.md"))
    assert "merges them into your chambers" not in text
    assert "`agrowtek:<sensor id>`" in text
    assert "`sensor_mappings` is accepted in the config but not used yet" in text


def test_worktrees_get_the_operator_claude_md():
    # Git-ignored, so neither a merge nor `git worktree add` carries it; Claude
    # Code copies the files .worktreeinclude names into each worktree it makes.
    assert re.search(r"^CLAUDE\.md$", _read(ROOT / ".gitignore"), re.M)
    include = [ln.strip() for ln in _read(ROOT / ".worktreeinclude").splitlines() if not ln.startswith("#")]
    assert "CLAUDE.md" in include
