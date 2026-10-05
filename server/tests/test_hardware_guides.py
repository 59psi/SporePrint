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
"""

import re
from pathlib import Path

import pytest

from app.builder.hardware_guides import _ESP32_CAM, _S3_PIN_MAP, TIERS
from app.builder.models import HardwareTier, usd
from app.builder.service import _HARDWARE_CONTRACT

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
            assert re.search(r"older setup\.sh", s), s


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
