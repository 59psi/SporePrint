"""The docs must describe the code, firmware and BOM that actually ship.

Every check here pins a claim that had drifted before the 2026-09 docs pass
(docs#2/#10-#13/#15/#16/#18/#19/#22/#24/#30, srv-auto#13, srv-hw#9/#15,
deps-infra#11/#21, fw-node#13/#15, fw-drivers-cam#15/#16): tier prices,
wiring-diagram labels, MQTT topics that never existed, the Tasmota FullTopic,
the S3 pin map, the secure-boot recipe, the Grafana port. When one fails, fix
the doc (or the code) so the two agree again; don't loosen the check.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.builder.hardware_guides import TIERS, TIER_ALL, TIER_RECOMMENDED
from app.db import SCHEMA
from app.hardware.service import PERIPHERAL_KEYS
from app.main import app as server_app
from app.species.profiles import BUILTIN_PROFILES

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"
GUIDE = DOCS / "hardware-build-guide.md"
FW_SECURITY = DOCS / "firmware-security.md"
DUAL_REPO = DOCS / "dual-repo-architecture.md"
MODELS = ROOT / "models"
MODELS_README = MODELS / "README.md"
SVGS = sorted(DOCS.glob("*.svg"))
TIER_SVGS = sorted(DOCS.glob("wiring-tier*.svg"))
SVG_NS = "{http://www.w3.org/2000/svg}"

# Markdown an operator or contributor follows (release history excluded:
# CHANGELOG entries describe what WAS true).
CURRENT_MD = [README, AGENTS, *sorted(DOCS.rglob("*.md")), ROOT / "models" / "README.md",
              ROOT / "firmware" / "test" / "README.md"]


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


@pytest.mark.parametrize("path", [README, GUIDE, AGENTS, *SVGS], ids=lambda p: p.name)
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
    for doc in (README, AGENTS):
        text = _read(doc)
        for n in re.findall(r"(\d+) (?:built-in )?species profiles", text):
            assert int(n) == n_species, f"{doc.name} says {n} species profiles, code has {n_species}"
        for n in re.findall(r"(\d+) (?:SQLite )?tables", text):
            assert int(n) == n_tables, f"{doc.name} says {n} tables, db.py has {n_tables}"
    assert f"{n_species} built-in species profiles" in _read(README)


def _server_modules() -> int:
    return sum(1 for p in (ROOT / "server" / "app").iterdir() if (p / "__init__.py").is_file())


def _api_operations() -> int:
    paths = server_app.openapi()["paths"]
    verbs = {"get", "post", "put", "patch", "delete"}
    return sum(1 for ops in paths.values() for verb in ops if verb in verbs)


# Every doc that states the server's size. dual-repo-architecture.md carried
# "17 router groups · 106 endpoints" long after the rest moved on.
_COUNT_DOCS = [README, AGENTS, DOCS / "data-flow.md", DUAL_REPO, DOCS / "architecture-overview.svg"]


@pytest.mark.parametrize("doc", _COUNT_DOCS, ids=lambda p: p.name)
def test_server_module_endpoint_and_table_counts_match_the_code(doc):
    n_modules, n_ops = _server_modules(), _api_operations()
    n_tables = len(set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA)))
    text = _read(doc)
    modules = re.findall(r"\b(\d+) (?:server )?(?:modules|router groups)\b", text)
    ops = re.findall(r"\b(\d+) (?:API )?(?:operations|endpoints)\b", text)
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

_PI_SIDE = ("Raspberry Pi", "microSD")


def _reusable_kits(tier) -> str:
    """The spools / assortments / kits share of a tier's price: every
    `shared` line except the Pi side (one per installation, not a kit)."""
    total = sum(c.line_cost() for c in tier.components
                if c.shared and not c.name.startswith(_PI_SIDE))
    return f"~${round(total)}"


@pytest.mark.parametrize("doc", [README, GUIDE], ids=lambda p: p.name)
def test_reusable_kit_share_matches_the_bom(doc):
    kits = [_reusable_kits(t) for t in TIERS]
    flat = re.sub(r"\s+", " ", _read(doc))
    if doc is GUIDE:
        assert f"| Reusable kits in the price | {' | '.join(kits)} |" in flat, kits
    else:
        assert " / ".join(kits) in flat, f"README should state the reusable kits as {kits}"
    assert "more than one chamber" in flat


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
