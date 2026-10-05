"""BOM invariants for the three Builder hardware tiers.

server/app/builder/hardware_guides.py is what the Builder page renders as the
shopping list, wiring table and setup steps. Every assertion here pins a
defect the 2026-09 hardware audit found in that file:

- quantities that did not match the circuits the wiring table draws (4
  MOSFETs for 6 gates, no 100 ohm gate resistors, no pull-up for the reed);
- estimated_cost strings that no longer matched the lines they summarise;
- wiring rows naming GPIOs outside the firmware pin map, and firmware_targets
  naming envs platformio.ini does not define;
- setup steps that could not produce a working install: setup.sh instead of
  install.sh (srv-hw#7), no per-node MQTT credential (srv-hw#8), Tasmota
  plugs without the sp-3p credential and FullTopic (srv-hw#9, docs#2,
  deps-infra#11), an S3 env with no S3 pin map (srv-hw#15);
- missing USB power for every node and camera (docs#25), M-F jumpers where the
  sensors chain over STEMMA QT, and capability bullets with no code behind
  them (docs#26).

The setup steps also mark commands, paths, payloads, topics, env names and
config keys as `code` for the Builder to render copyable; every marked span
must name something this repo has (see "setup-step code spans").
"""

import functools
import json
import os
import re
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.builder.hardware_guides import _ESP32_CAM, _S3_PIN_MAP, TIERS
from app.builder.models import HardwareTier, usd
from app.builder.service import _HARDWARE_CONTRACT
from app.main import app as server_app

REPO_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = REPO_ROOT / "firmware"
BOARD_PROFILE = FIRMWARE / "boards" / "board_profile_esp32dev.h"
S3_PROFILE = FIRMWARE / "boards" / "board_profile_esp32s3.h"
PERSONALITY = FIRMWARE / "lib" / "sp_core" / "personality.h"
PLATFORMIO_INI = FIRMWARE / "platformio.ini"
PROVISIONER = FIRMWARE / "lib" / "sp_device" / "wifi_provisioner.cpp"

TIER_IDS = [t.id for t in TIERS]
_GPIO_RE = re.compile(r"GPIO\s*(\d+(?:\s*/\s*\d+)*)")


def _read(path: Path) -> str:
    # A guard that silently skips is not a guard: fail loudly if the tree moved.
    assert path.is_file(), f"{path} missing — firmware tree moved?"
    return path.read_text()


def _tier(tier_id: str) -> HardwareTier:
    return next(t for t in TIERS if t.id == tier_id)


def _qty(tier: HardwareTier, pattern: str) -> int:
    """Total quantity of the lines whose name matches ``pattern``."""
    rx = re.compile(pattern, re.I)
    return sum(c.quantity for c in tier.components if rx.search(c.name))


def _pin_map(path: Path) -> dict[str, list[int]]:
    """``#define SP_* <int>`` pins and the SP_CHANNEL_PINS list of a board profile."""
    text = _read(path)
    pins: dict[str, list[int]] = {}
    for name, value in re.findall(r"#define\s+(SP_\w+)\s+(-?\d+)\b", text):
        if "PIN" in name or "UART" in name:
            pins[name] = [int(value)]
    chan = re.search(r"#define\s+SP_CHANNEL_PINS\s*\{([^}]*)\}", text)
    assert chan, f"SP_CHANNEL_PINS missing from {path.name}"
    pins["SP_CHANNEL_PINS"] = [int(p) for p in chan.group(1).split(",")]
    return pins


def _gpios(text: str) -> list[int]:
    out: list[int] = []
    for group in _GPIO_RE.findall(text):
        out.extend(int(p) for p in re.split(r"\s*/\s*", group))
    return out


def _all_text(tier: HardwareTier) -> str:
    parts = [*tier.setup_steps]
    for c in tier.components:
        parts += [c.name, c.role, c.notes]
    return "\n".join(parts)


# ── URLs and prices ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_every_url_is_https_and_unique_per_line(tier_id):
    tier = _tier(tier_id)
    urls = [c.url for c in tier.components]
    for c in tier.components:
        assert c.url.startswith("https://"), f"{c.name}: {c.url!r} is not https"
    dupes = {u for u in urls if urls.count(u) > 1}
    assert not dupes, f"{tier_id}: several BOM lines share a url: {sorted(dupes)}"


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_every_price_parses(tier_id):
    for c in _tier(tier_id).components:
        assert usd(c.price_approx) > 0, c.name
        if c.pack_price:
            assert usd(c.pack_price) >= usd(c.price_approx), (
                f"{c.name}: pack_price {c.pack_price} is below the unit price"
            )


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_estimated_cost_matches_the_components(tier_id):
    tier = _tier(tier_id)
    m = re.fullmatch(r"~\$(\d[\d,]*)", tier.estimated_cost)
    assert m, f"{tier_id}: estimated_cost {tier.estimated_cost!r} is not '~$N'"
    stated = float(m.group(1).replace(",", ""))
    computed = tier.parts_cost()
    assert abs(stated - computed) <= 0.10 * computed, (
        f"{tier_id}: estimated_cost {tier.estimated_cost} vs price x quantity "
        f"(packs counted once) = ${computed:.2f}"
    )


def test_pack_priced_passives_are_counted_once():
    """A 125-pack of diodes is bought once, whatever the quantity."""
    tier = _tier("all_the_things")
    diode = next(c for c in tier.components if "UF4007" in c.name)
    assert diode.pack_price
    assert diode.line_cost() == usd(diode.pack_price)


# ── switch-stage quantities ─────────────────────────────────────────────────


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_gate_resistor_per_mosfet(tier_id):
    tier = _tier(tier_id)
    assert _qty(tier, r"100\s*(Ω|ohm)") == _qty(tier, r"IRLZ44N")


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_pull_down_per_gate_plus_reed_pull_up(tier_id):
    tier = _tier(tier_id)
    reed = 1 if _qty(tier, r"reed|door contact") else 0
    assert _qty(tier, r"\b10K\b") == _qty(tier, r"IRLZ44N") + reed


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_mosfet_count_matches_the_wired_gates(tier_id):
    tier = _tier(tier_id)
    gates = {
        (w.from_device, g)
        for w in tier.wiring
        if "IRLZ44N" in w.to_device and "Gate" in w.to_device
        for g in _gpios(w.from_pin)
    }
    assert _qty(tier, r"IRLZ44N") == len(gates)


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_flyback_diodes_only_on_inductive_relay_channels(tier_id):
    """Fans and the pump are inductive; LED strips are resistive and need none."""
    tier = _tier(tier_id)
    relay_channels = {
        g for w in tier.wiring
        if w.from_device.startswith("ESP32 (Relay)") and "IRLZ44N" in w.to_device
        for g in _gpios(w.from_pin)
    }
    assert _qty(tier, r"flyback|UF4007|1N4007") == len(relay_channels)


# ── wiring vs firmware ──────────────────────────────────────────────────────


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_firmware_targets_exist_in_platformio(tier_id):
    envs = set(re.findall(r"^\[env:([\w-]+)\]", _read(PLATFORMIO_INI), re.M))
    for target in _tier(tier_id).firmware_targets:
        assert target in envs, f"firmware target {target!r} is not an env in platformio.ini"


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_every_env_named_in_the_text_exists(tier_id):
    """`-e <env>` in a step, or a node_esp32* env named in a note, must build."""
    envs = set(re.findall(r"^\[env:([\w-]+)\]", _read(PLATFORMIO_INI), re.M))
    text = _all_text(_tier(tier_id))
    named = set(re.findall(r"-e (\w+)", text)) | set(re.findall(r"\b(node_esp32\w*)", text))
    assert named, "no firmware env named anywhere"
    assert named <= envs, f"envs not in platformio.ini: {sorted(named - envs)}"


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_every_wired_gpio_is_in_the_firmware_pin_map(tier_id):
    allowed = {p for pins in _pin_map(BOARD_PROFILE).values() for p in pins}
    for w in _tier(tier_id).wiring:
        for field in (w.from_pin, w.to_pin, w.note):
            for g in _gpios(field):
                assert g in allowed, (
                    f"{tier_id}: {w.from_device} → {w.to_device} uses GPIO {g}, "
                    f"which board_profile_esp32dev.h does not define"
                )


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_channel_rows_follow_the_personality_channel_order(tier_id):
    """GPIO n of SP_CHANNEL_PINS carries personality channel n (personality.h)."""
    chan_pins = _pin_map(BOARD_PROFILE)["SP_CHANNEL_PINS"]
    banks = re.findall(r"names\[4\]\s*=\s*\{([^}]*)\}", _read(PERSONALITY))
    relay, lighting = ([n.strip().strip('"') for n in b.split(",")] for b in banks)
    for w in _tier(tier_id).wiring:
        bank = relay if w.from_device.startswith("ESP32 (Relay)") else (
            lighting if w.from_device.startswith("ESP32 (Lighting)") else None)
        if bank is None:
            continue
        for g in _gpios(w.from_pin):
            if g not in chan_pins:
                continue  # HX711 / reed rows on the relay node
            expected = bank[chan_pins.index(g)].replace("_", "-")
            label = f"{w.from_pin} {w.to_device} {w.note}".lower()
            assert expected in label, f"GPIO {g} row should carry channel {expected!r}: {label!r}"


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_climate_sensors_daisy_chain_over_stemma_qt(tier_id):
    """One QT-to-sockets lead per climate node, QT-QT cables between sensors,
    and exactly one ESP32 SDA row per climate node (a chain, not a star)."""
    tier = _tier(tier_id)
    nodes = {"bare_bones": 1, "recommended": 1, "all_the_things": 2}[tier_id]
    sensors_per_node = {"bare_bones": 2, "recommended": 3, "all_the_things": 3}[tier_id]
    assert _qty(tier, r"STEMMA QT.*female") == nodes
    assert _qty(tier, r"STEMMA QT.*QT-QT") == nodes * (sensors_per_node - 1)
    assert not _qty(tier, r"jumper wires \(M-F"), "M-F jumpers cannot mate the male-header sensors"
    sda_rows = [
        w for w in tier.wiring
        if w.from_device.startswith("ESP32") and "Relay" not in w.from_device
        and "Lighting" not in w.from_device and 21 in _gpios(w.from_pin)
    ]
    assert len(sda_rows) == nodes, [f"{w.from_device} → {w.to_device}" for w in sda_rows]


# ── power ───────────────────────────────────────────────────────────────────


def _pack(name: str) -> int:
    m = re.search(r"(\d+)-pack", name, re.I)
    return int(m.group(1)) if m else 1


@pytest.mark.parametrize(
    "tier_id,nodes,cams",
    [("bare_bones", 1, 0), ("recommended", 3, 1), ("all_the_things", 4, 2)],
)
def test_every_board_has_usb_power_and_a_cable(tier_id, nodes, cams):
    tier = _tier(tier_id)
    bricks = sum(c.quantity * _pack(c.name) for c in tier.components if "USB Wall Charger" in c.name)
    usb_c = sum(c.quantity * _pack(c.name) for c in tier.components if "USB-A to USB-C" in c.name)
    micro = sum(c.quantity * _pack(c.name) for c in tier.components if "USB-A to Micro-USB" in c.name)
    assert bricks >= nodes + cams
    assert usb_c >= nodes
    assert micro >= cams
    for c in tier.components:
        assert "ESP32-S3" not in c.role, f"{c.name}: the BOM board is the WROOM-32"


# ── setup steps ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_install_uses_install_sh_not_setup_sh(tier_id):
    steps = _tier(tier_id).setup_steps
    assert any("./install.sh" in s for s in steps)
    for s in steps:
        if re.search(r"(?<![\w-])setup\.sh", s):
            # Only allowed as a warning: it is the developer script and turns
            # on bearer auth the shipped dashboard never sends.
            assert "developer" in s.lower(), s


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_node_mqtt_credential_comes_before_the_portal(tier_id):
    steps = _tier(tier_id).setup_steps
    cred = next(i for i, s in enumerate(steps) if "./scripts/add-node-mqtt-user.sh" in s)
    portal = next(i for i, s in enumerate(steps) if "SporePrint-Setup" in s)
    assert cred < portal
    assert "MQTT username" in steps[portal]


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_tasmota_plug_setup_sets_credentials_and_full_topic(tier_id):
    tier = _tier(tier_id)
    assert _qty(tier, r"Tasmota")
    plug_steps = [s for s in tier.setup_steps if "Tasmota" in s and "Configuration" in s]
    assert plug_steps, "no Tasmota MQTT setup step"
    for s in plug_steps:
        assert "sp-3p" in s
        assert "SPOREPRINT_MQTT_3P_PASSWORD" in s
        assert "tasmota/%topic%/%prefix%/" in s


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_s3_mentions_point_at_the_s3_pin_map(tier_id):
    s3 = _pin_map(S3_PROFILE)
    sda, scl = s3["SP_PIN_I2C_SDA"][0], s3["SP_PIN_I2C_SCL"][0]
    for text in [*_tier(tier_id).setup_steps, *(c.notes for c in _tier(tier_id).components)]:
        if "node_esp32s3" not in text:
            continue
        assert "board_profile_esp32s3.h" in text, text
        assert f"SDA {sda}" in text and f"SCL {scl}" in text, text


# ── capability claims ───────────────────────────────────────────────────────

# Phrases for features the Pi server does not implement (docs#26). Re-adding
# one needs the code first.
_UNIMPLEMENTED = [
    r"kWh", r"PID", r"[Tt]imelapse generation", r"[Qq]uiet hours", r"EXIF",
    r"diverge", r"[Aa]utomatic sensor fallback", r"[Cc]orrelation (analysis|reports)",
]


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_capabilities_only_claim_implemented_features(tier_id):
    tier = _tier(tier_id)
    items = [*tier.what_you_get, *(i for g in tier.capability_groups for i in g.items)]
    for item in items:
        for pat in _UNIMPLEMENTED:
            assert not re.search(pat, item), f"{tier_id}: {item!r} claims an unimplemented feature"


# ── final-review wording (consistency pass) ─────────────────────────────────


def test_builder_contract_names_the_bom_camera_packs_sensor():
    """The Builder's Assistant must not say the BOM pack ships OV3660: the
    pinned AITRIP 2-pack ships OV2640 (OV3660 is the HiLetgo/Aideepen packs)."""
    m = re.search(r"AITRIP 2-pack: two AI-Thinker ESP32-CAMs \((OV\d{4})\)", _ESP32_CAM.notes)
    assert m, "the BOM camera line no longer names the AITRIP pack's sensor"
    bom_sensor = m.group(1)
    assert f"{bom_sensor} (the BOM AITRIP 2-pack)" in _HARDWARE_CONTRACT
    for other in {"OV2640", "OV3660", "OV5640"} - {bom_sensor}:
        assert not re.search(rf"{other} \([^)]*BOM", _HARDWARE_CONTRACT), (
            f"the contract ties {other} to the BOM pack")
    assert "auto-detected" in _HARDWARE_CONTRACT


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_setup_sh_warning_matches_the_current_script(tier_id):
    """setup.sh runs LAN-trust now; only an OLDER setup.sh run left an API key."""
    for s in _tier(tier_id).setup_steps:
        if not re.search(r"(?<![\w-])setup\.sh", s):
            continue
        assert "API key it generates" not in s, s
        if "API key" in s:
            assert re.search(r"older `?setup\.sh", s), s


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_camera_tiers_teach_the_io13_portal_gesture(tier_id):
    """The ESP32-CAM has no BOOT gesture (GPIO 0 is XCLK): its portal gesture
    is IO13 shorted to GND for 3-10 s (board_profile_esp32cam.h)."""
    cam_pin = re.search(r"#define SP_PIN_FACTORY_RESET (\d+)",
                        _read(FIRMWARE / "boards" / "board_profile_esp32cam.h")).group(1)
    tier = _tier(tier_id)
    portal = next(s for s in tier.setup_steps if "SporePrint-Setup" in s)
    if not _qty(tier, r"ESP32-CAM"):
        assert f"IO{cam_pin}" not in portal
        return
    assert re.search(rf"IO{cam_pin}[^.]*GND[^.]*3-10 s", portal), portal
    assert re.search(r"[Cc]amera[^.]*no personality", portal), portal


def test_s3_pin_map_gives_the_mhz19_wire_direction():
    """SP_UART_CO2_RX is the ESP32's RX: the sensor's TX goes to it."""
    s3 = _pin_map(S3_PROFILE)
    rx, tx = s3["SP_UART_CO2_RX"][0], s3["SP_UART_CO2_TX"][0]
    assert f"MH-Z19C TX→{rx} / RX→{tx}" in _S3_PIN_MAP
    assert "RX/TX" not in _S3_PIN_MAP


def test_tier3_esp32_quantity_is_the_pinned_six_pack():
    tier = _tier("all_the_things")
    esp = next(c for c in tier.components if c.name.startswith("ESP32-WROOM-32"))
    assert "6-pack (B0DSZBH9N9" in esp.notes
    assert esp.quantity == 6, "the pinned buy is a 6-pack: 4 nodes + 2 spares"
    assert esp.line_cost() == usd("$30")


def test_10k_example_is_a_quarter_watt_part():
    """relay_board_mount's resistor seats fit 1/4 W bodies (6.3 x Ø2.4)."""
    header = _read(REPO_ROOT / "models" / "relay_board_mount.scad")
    assert "1/4 W axial" in header
    for tier in TIERS:
        for c in tier.components:
            if re.search(r"\b10K\b", c.name):
                assert "B0BDKY8VQG" not in c.notes, "B0BDKY8VQG is a 1/2 W part"
                assert "1/4 W" in c.notes and "1/2 W" in c.notes, c.notes


# ── Cabling, connectors and assembly consumables ────────────────
# The BOM used to stop at the boards: no wire, fuses, connectors, power
# strip, inserts or screws, so a builder could not finish from the list.

_PSU_AMPS = {"recommended": 5.0, "all_the_things": 10.0}
_LIGHTING_FUSE = {"recommended": "5 A", "all_the_things": "7.5 A"}


def _has(tier: HardwareTier, pattern: str) -> bool:
    return _qty(tier, pattern) > 0


@pytest.mark.parametrize("tier_id", ["recommended", "all_the_things"])
def test_12v_tiers_carry_the_whole_distribution_set(tier_id):
    tier = _tier(tier_id)
    for pattern in (r"DC Barrel Pigtail", r"\bWAGO 221\b", r"Fuse Holders", r"Fuse Assortment",
                    r"18 AWG 2-Conductor", r"22 AWG Stranded Hookup", r"Fan Extension",
                    r"Heat Shrink", r"Zip Ties, 18", r"VELCRO", r"Solder"):
        assert _has(tier, pattern), f"{tier_id}: missing {pattern}"


@pytest.mark.parametrize("tier_id", ["recommended", "all_the_things"])
def test_fuse_ratings_match_the_psu(tier_id):
    tier = _tier(tier_id)
    rows = [w for w in tier.wiring if "fuse" in w.to_device.lower()]
    relay = [w for w in rows if "relay" in w.to_device.lower()]
    lighting = [w for w in rows if "lighting" in w.to_device.lower()]
    assert len(relay) == 1 and "3 A" in relay[0].to_device
    assert len(lighting) == 1 and _LIGHTING_FUSE[tier_id] in lighting[0].to_device
    amps = float(_LIGHTING_FUSE[tier_id].split()[0])
    assert amps <= _PSU_AMPS[tier_id], "a fuse above the PSU rating never blows"
    # The setup step says the same thing as the wiring rows.
    steps = " ".join(tier.setup_steps)
    assert "3 A to the relay board" in steps
    assert f"{_LIGHTING_FUSE[tier_id]} to the lighting board" in steps


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_every_tier_can_mount_and_route_what_it_prints(tier_id):
    tier = _tier(tier_id)
    for pattern in (r"Zip Ties", r"Grommet", r"Heat-Set Insert", r"M2\.5 Socket Head",
                    r"M3 x 6 mm Socket Head", r"Socket Head Screw Kit M2\.5-M8", r"Surge Protector"):
        assert _has(tier, pattern), f"{tier_id}: missing {pattern}"
    # M2.5 inserts are separate everywhere: the ruthex assortment has none.
    assert _has(tier, r"Heat-Set Inserts M2\.5")
    if tier_id != "bare_bones":
        assert _has(tier, r"M4 Socket Head Screw Kit"), "fan_duct needs M4 x 35"


@pytest.mark.parametrize("tier_id,in_chamber_nodes,cams", [
    ("bare_bones", 1, 0), ("recommended", 1, 1), ("all_the_things", 2, 2),
])
def test_in_chamber_boards_get_six_foot_cables(tier_id, in_chamber_nodes, cams):
    tier = _tier(tier_id)
    assert _qty(tier, r"USB-C Data Cable, 6 ft") == in_chamber_nodes
    micro = [c for c in tier.components if "Micro-USB Data Cable, 6 ft (2-pack)" in c.name]
    assert sum(c.quantity * 2 for c in micro) >= cams
    assert not _has(tier, r"Micro-USB Data Cable, 3 ft")


def test_tier3_runs_and_plumbing():
    tier = _tier("all_the_things")
    assert _has(tier, r"22 AWG 4-Conductor"), "HX711 + door contact runs back to the relay node"
    assert _has(tier, r"Food-Grade Silicone Tubing"), "the pump's included tubing is not food-safe"
    assert _has(tier, r"Set Screws"), "hx711_scale overload stops"
    notes = {w.to_pin: w.note for w in tier.wiring if w.to_device == "HX711"}
    assert "22/4 cable: yellow" in notes["DOUT (DATA)"] and "22/4 cable: white" in notes["SCK (CLK)"]


def test_surge_strip_has_an_outlet_per_brick():
    # Pi PSU + 12V brick + USB cubes + smart plugs must fit the chosen strip.
    outlets = {"bare_bones": 6, "recommended": 12, "all_the_things": 12}
    for tier in TIERS:
        cubes = sum(c.quantity * 2 for c in tier.components if c.name.startswith("USB Wall Charger"))
        bricks = 1 + (1 if _has(tier, r"12V Power Supply") else 0)
        plugs = _qty(tier, r"Tasmota")
        assert bricks + cubes + plugs <= outlets[tier.id], tier.id


def test_shared_lines_are_kits_or_pi_side_only():
    """`shared` lines are not multiplied per chamber in the dashboard."""
    for tier in TIERS:
        for c in tier.components:
            if c.category in ("controller", "sensor", "actuator", "plug"):
                assert not c.shared or c.name.startswith("Raspberry Pi"), c.name
            if c.shared:
                assert (c.category in ("wiring", "hardware", "misc")
                        or c.name.startswith(("Raspberry Pi", "microSD"))), c.name


# ── setup-step code spans ───────────────────────────────────────────────────
#
# The Builder renders each `backticked` span of a setup step as copyable code,
# so every span is something a reader pastes or types — it must name what
# this repo really has. _check_span() sorts a span into a kind and checks it:
#
#   URL            a raw GitHub path that exists here; the clone URL install.sh
#                  uses; http://<pi>:PORT on a port docker-compose.yml publishes
#   API call       "POST /api/..." is a route + method the server serves
#   JSON payload   a cmd/config body: top-level keys the node firmware's
#                  handle_config_cmd reads, nested keys sp_core knows
#   Tasmota        Backlog: MqttPort is a broker listener, MqttUser an ACL user,
#                  Topic t a plug-t rule target. A FullTopic must reach the Pi
#                  (sp-3p may publish it, the server subscribes) — except
#                  Tasmota's default, which the steps say the broker drops
#   env name       SPOREPRINT_* that docker-compose.yml passes or install.sh sets
#   -D / x="y"     an OpenSCAD parameter a model declares, with a valid value
#   path           exists (repo root, models/ or scripts/); .env is install.sh's
#   cmd/<x>        an endpoint the node's command router serves
#   node id        an id add-node-mqtt-user.sh accepts
#   shell command  every command of a && / | chain: scripts exist and are
#                  executable, cd targets exist, pio envs and compose
#                  services exist, git clone fetches this repo
#   anything else  a model name, or appears verbatim in the code the Pi runs

_CODE_RE = re.compile(r"`([^`]*)`")
MODELS = REPO_ROOT / "models"
COMPOSE = REPO_ROOT / "docker-compose.yml"
INSTALL_SH = REPO_ROOT / "install.sh"
ACL = REPO_ROOT / "config" / "mosquitto" / "acl.conf"
MOSQUITTO_CONF = REPO_ROOT / "config" / "mosquitto" / "mosquitto.conf"
NODE_MAIN = FIRMWARE / "src" / "node" / "main.cpp"
CMD_ROUTER = FIRMWARE / "lib" / "sp_core" / "cmd_router.h"
ADD_NODE_USER = REPO_ROOT / "scripts" / "add-node-mqtt-user.sh"
SERVER_APP = REPO_ROOT / "server" / "app"
_PATH_SUFFIXES = {".sh", ".scad", ".h", ".cpp", ".md", ".py", ".ini", ".svg", ".csv", ".yml"}
# Tasmota FullTopic placeholders, expanded to the state topic a plug publishes.
_TASMOTA_EXPAND = {"%topic%": "humidifier", "<topic>": "humidifier", "%prefix%": "stat"}


def _mqtt_match(pattern: str, topic: str) -> bool:
    p, t = pattern.split("/"), topic.split("/")
    for i, seg in enumerate(p):
        if seg == "#":
            return True
        if i >= len(t) or (seg != "+" and seg != t[i]):
            return False
    return len(p) == len(t)


def _acl_grants(text: str) -> dict[str, list[tuple[str, str]]]:
    """{user: [(access, topic filter)]} from the broker's acl.conf."""
    grants: dict[str, list[tuple[str, str]]] = {}
    user = None
    for line in text.splitlines():
        if m := re.match(r"user\s+(\S+)", line):
            user = m.group(1)
            grants[user] = []
        elif line.startswith("pattern"):
            user = None
        elif (m := re.match(r"topic\s+(read|write|readwrite)\s+(\S+)", line)) and user:
            grants[user].append((m.group(1), m.group(2)))
    return grants


@functools.cache
def _facts() -> SimpleNamespace:
    compose = yaml.safe_load(_read(COMPOSE))
    services = compose["services"]
    published = {str(p).split(":")[0] for s in services.values() for p in s.get("ports", [])}
    install = _read(INSTALL_SH)
    repo_url = re.search(r'REPO_URL="\$\{SPOREPRINT_REPO_URL:-([^}]+)\}"', install)
    assert repo_url, "install.sh no longer names its default repo URL"
    scad_decls: dict[str, list[str]] = {}
    for f in sorted([*MODELS.glob("*.scad"), *MODELS.glob("lib/*.scad")]):
        text = f.read_text()
        for name in set(re.findall(r"^(\w+)\s*=", text, re.M)):
            scad_decls.setdefault(name, []).append(text)
    main = _read(NODE_MAIN)
    config_cmd = re.search(r"static void handle_config_cmd\(.*?\n}\n", main, re.S)
    assert config_cmd, "handle_config_cmd moved out of the node firmware's main.cpp"
    node_id_re = re.search(r'NODE_ID" =~ (\^\S+\$) \]\]', _read(ADD_NODE_USER))
    assert node_id_re, "add-node-mqtt-user.sh no longer validates the node id"
    # What the Pi actually runs: firmware, models, broker config, compose,
    # install + scripts, and the server outside the Builder's own prose.
    corpus = [_read(PLATFORMIO_INI), _read(COMPOSE), install,
              *(p.read_text() for p in (REPO_ROOT / "config" / "mosquitto").glob("*.conf")),
              *(p.read_text() for p in (REPO_ROOT / "scripts").glob("*.sh")),
              *(p.read_text() for p in MODELS.rglob("*.scad")),
              *(p.read_text() for p in FIRMWARE.glob("[bls]*/**/*") if p.suffix in (".h", ".cpp")),
              *(p.read_text() for p in SERVER_APP.rglob("*.py") if "builder" not in p.parts)]
    return SimpleNamespace(
        envs=set(re.findall(r"^\[env:([\w-]+)\]", _read(PLATFORMIO_INI), re.M)),
        services=set(services),
        published_ports=published,
        install=install,
        compose_text=_read(COMPOSE),
        repo_url=repo_url.group(1),
        routes={path: set(ops) for path, ops in server_app.openapi()["paths"].items()},
        scad_decls=scad_decls,
        model_stems={p.stem for p in MODELS.glob("*.scad")},
        config_cmd=config_cmd.group(0),
        sp_core="\n".join(p.read_text() for p in (FIRMWARE / "lib" / "sp_core").glob("*.h")),
        cmd_router=_read(CMD_ROUTER),
        acl=_acl_grants(_read(ACL)),
        listeners=set(re.findall(r"^listener\s+(\d+)", _read(MOSQUITTO_CONF), re.M)),
        mqtt_py=_read(SERVER_APP / "mqtt.py"),
        rule_targets=set(re.findall(r'target="([\w-]+)"',
                                    _read(SERVER_APP / "automation" / "templates.py"))),
        node_id_re=re.compile(node_id_re.group(1)),
        corpus="\n".join(corpus),
    )


def _check_url(url: str, f: SimpleNamespace) -> str | None:
    slug = f.repo_url.removeprefix("https://github.com/").removesuffix(".git")
    if m := re.fullmatch(r"https://raw\.githubusercontent\.com/([^/]+/[^/]+)/main/(.+)", url):
        if m.group(1) != slug:
            return f"raw URL is not this repo ({slug})"
        return None if (REPO_ROOT / m.group(2)).is_file() else f"{m.group(2)} is not in the repo"
    if url.startswith("https://github.com/"):
        return None if url == f.repo_url else f"not the repo install.sh clones ({f.repo_url})"
    if m := re.fullmatch(r"http://(<[^>]+>|sporeprint\.local):(\d+)/?", url):
        return None if m.group(2) in f.published_ports else (
            f"port {m.group(2)} is not published by docker-compose.yml")
    return "unrecognised URL"


def _check_api(method: str, path: str, f: SimpleNamespace) -> str | None:
    for route, ops in f.routes.items():
        if re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", route), path) and method.lower() in ops:
            return None
    return "no such route on the server"


def _check_json(payload: str, f: SimpleNamespace) -> str | None:
    body = re.sub(r"<[^>]+>", "1", payload)
    body = re.sub(r":\s*N\b", ": 1", body)
    try:
        doc = json.loads(body)
    except json.JSONDecodeError as e:
        return f"not JSON ({e})"
    if not isinstance(doc, dict):
        return "not a JSON object"
    for key, value in doc.items():
        if f'doc["{key}"]' not in f.config_cmd:
            return f"the node's handle_config_cmd does not read {key!r}"
        for sub in value if isinstance(value, dict) else ():
            if f'"{sub}"' not in f.sp_core:
                return f"sp_core knows no {key}.{sub!r}"
    return None


def _check_scad_param(assign: str, f: SimpleNamespace) -> str | None:
    name, _, value = assign.partition("=")
    files = f.scad_decls.get(name)
    if not files:
        return f"no model declares the parameter {name!r}"
    if value.startswith('"'):
        if not any(value in text for text in files):
            return f"{value} is not an option of {name}"
    elif value not in ("true", "false"):
        return f"unexpected value {value!r}"
    return None


def _check_tasmota_topic(topic: str, before: str, f: SimpleNamespace) -> str | None:
    state = topic
    for k, v in _TASMOTA_EXPAND.items():
        state = state.replace(k, v)
    if state.endswith("/"):
        state += "POWER"
    granted = any(_mqtt_match(t, state) for access, t in f.acl.get("sp-3p", ())
                  if "write" in access)
    heard = any(_mqtt_match(t, state) for t in re.findall(r'subscribe\("([^"]+)"\)', f.mqtt_py))
    if re.search(r"(default|publishes)\s*$", before):
        # The step names this as what NOT to use: the broker must refuse it.
        return f"{state} is accepted — the step says the broker drops it" if granted else None
    if not granted:
        return f"the sp-3p plug login may not publish {state}"
    return None if heard else f"the server does not subscribe to {state}"


def _check_backlog(cmd: str, before: str, f: SimpleNamespace) -> str | None:
    settings = dict(part.strip().split(" ", 1) for part in cmd.removeprefix("Backlog ").split(";"))
    unknown = set(settings) - {"MqttHost", "MqttPort", "MqttUser", "MqttPassword", "Topic", "FullTopic"}
    if unknown:
        return f"unexpected Tasmota commands {sorted(unknown)}"
    if settings.get("MqttPort") not in f.listeners:
        return f"MqttPort {settings.get('MqttPort')} is not a broker listener"
    if settings.get("MqttUser") not in f.acl:
        return f"MqttUser {settings.get('MqttUser')} has no ACL"
    if f"plug-{settings.get('Topic')}" not in f.rule_targets:
        return f"no built-in rule drives plug-{settings.get('Topic')}"
    return _check_tasmota_topic(settings.get("FullTopic", ""), "", f)


def _check_path(path: str, f: SimpleNamespace) -> str | None:
    if path == ".env":
        return None if ".env" in f.install else "install.sh does not write .env"
    for base in (REPO_ROOT, MODELS, REPO_ROOT / "scripts"):
        if (base / path).exists() and (not path.endswith("/") or (base / path).is_dir()):
            return None
    return "no such file in the repo"


def _check_shell(chain: str, f: SimpleNamespace) -> str | None:
    cwd, clones = REPO_ROOT, {}
    for cmd in re.split(r"\s*(?:&&|\|)\s*", chain):
        words = shlex.split(cmd)
        prog, args = words[0], words[1:]
        if prog == "curl":
            for url in (a for a in args if "://" in a):
                if err := _check_url(url, f):
                    return f"{url}: {err}"
        elif prog == "bash":
            pass
        elif prog == "git":
            if args[:1] != ["clone"] or args[1] != f.repo_url:
                return f"{cmd!r} does not clone {f.repo_url}"
            clones[Path(args[1]).stem] = REPO_ROOT
        elif prog == "cd":
            cwd = clones.get(args[0]) or cwd / args[0]
            if not cwd.is_dir():
                return f"cd {args[0]}: no such directory"
        elif prog == "pio":
            env = args[args.index("-e") + 1] if "-e" in args else None
            if not (cwd / "platformio.ini").is_file():
                return f"{cmd!r} runs outside a PlatformIO project"
            if env not in f.envs:
                return f"pio env {env!r} is not in platformio.ini"
        elif prog == "pip":
            if args != ["install", "platformio"]:
                return f"unexpected pip command {cmd!r}"
        elif prog == "docker":
            if args[:1] != ["compose"] or not (cwd / "docker-compose.yml").is_file():
                return f"{cmd!r} is not docker compose in the repo"
            services = [a for a in args[2:] if not a.startswith("-")]
            if not set(services) <= f.services:
                return f"compose services {sorted(set(services) - f.services)} do not exist"
        elif prog.startswith("./"):
            script = cwd / prog
            if not script.is_file() or not os.access(script, os.X_OK):
                return f"{prog} is not an executable script in the repo"
        else:
            return f"unknown command {prog!r}"
    return None


def _check_span(span: str, before: str, f: SimpleNamespace) -> str | None:
    if span.startswith(("http://", "https://")):
        return _check_url(span, f)
    if m := re.fullmatch(r"(GET|POST|PUT|PATCH|DELETE) (/api/\S+)", span):
        return _check_api(m.group(1), m.group(2), f)
    if span.startswith("{"):
        return _check_json(span, f)
    if span.startswith("Backlog "):
        return _check_backlog(span, before, f)
    if m := re.fullmatch(r"(SPOREPRINT_[A-Z0-9_]+)(=\S+)?", span):
        return None if m.group(1) in f.compose_text or m.group(1) in f.install else (
            f"{m.group(1)} is neither passed by docker-compose.yml nor set by install.sh")
    if span.startswith("-D "):
        return _check_scad_param(shlex.split(span)[1], f)
    if re.fullmatch(r'\w+=("[^"]*"|\w+)', span):
        return _check_scad_param(span, f)
    if "%" in span or re.match(r"(stat|tele|cmnd)/", span):
        return _check_tasmota_topic(span, before, f)
    if m := re.fullmatch(r"cmd/(\w+)", span):
        return None if f'"{m.group(1)}"' in f.cmd_router else "the node serves no such cmd endpoint"
    if " " in span:
        return _check_shell(span, f)
    if span == ".env" or span.startswith("./") or span.endswith("/") \
            or Path(span).suffix in _PATH_SUFFIXES:
        return _check_path(span, f)
    if re.fullmatch(r"(climate|relay|lighting|cam)-\d+", span):
        return None if f.node_id_re.fullmatch(span) else "add-node-mqtt-user.sh rejects this id"
    if span in f.model_stems:
        return None
    if re.search(rf"(?<![\w-]){re.escape(span)}(?![\w-])", f.corpus):
        return None
    return "names nothing in the repo"


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_setup_step_code_marks_are_balanced(tier_id):
    for i, step in enumerate(_tier(tier_id).setup_steps):
        assert step.count("`") % 2 == 0, f"step {i}: unbalanced backtick in {step!r}"
        assert "``" not in step, f"step {i}: empty or doubled code mark in {step!r}"
        for span in _CODE_RE.findall(step):
            assert span and span == span.strip(), f"step {i}: code span {span!r} has edge spaces"


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_only_setup_steps_carry_code_marks(tier_id):
    """Component notes, wiring rows and capability text render as plain text."""
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from strings(v)
        elif isinstance(value, list):
            for v in value:
                yield from strings(v)

    data = _tier(tier_id).model_dump(exclude={"setup_steps"})
    marked = [s for s in strings(data) if "`" in s]
    assert not marked, f"{tier_id}: code marks outside the setup steps: {marked}"


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_every_code_span_names_something_the_repo_has(tier_id):
    f = _facts()
    problems = []
    for i, step in enumerate(_tier(tier_id).setup_steps):
        for m in _CODE_RE.finditer(step):
            if err := _check_span(m.group(1), step[:m.start()], f):
                problems.append(f"step {i}: `{m.group(1)}` — {err}")
    assert not problems, "\n".join(problems)


def test_setup_steps_mark_the_commands_people_copy():
    """The commands a reader has to run are marked, not buried in prose."""
    must_mark = ["curl -fsSL", "pio run -t upload -e node_esp32", "./scripts/add-node-mqtt-user.sh",
                 "docker compose up -d server", "tasmota/%topic%/%prefix%/"]
    for tier in TIERS:
        spans = [s for step in tier.setup_steps for s in _CODE_RE.findall(step)]
        for cmd in must_mark:
            assert any(cmd in s for s in spans), f"{tier.id}: {cmd!r} is not in a code span"
        prose = "\n".join(_CODE_RE.sub("", step) for step in tier.setup_steps)
        for bare in ("pio run", "docker compose", "./scripts/", "curl ", "cmd/config", "{\""):
            assert bare not in prose, f"{tier.id}: {bare!r} appears outside a code span"
