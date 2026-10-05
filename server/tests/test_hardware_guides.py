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
import math
import os
import re
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.builder.hardware_guides import _ESP32_CAM, _S3_PIN_MAP, TIERS
from app.builder.models import Component, HardwareTier, usd
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


# ── pack-sold lines and the chamber multiplier ─────────────────────────────
#
# A pack-sold line counts UNITS: quantity is what the tier needs per chamber,
# price_approx the per-unit price within the pinned pack, pack_price that
# pack's price and pack_size its units. N chambers buy ceil(quantity x N /
# pack_size) packs. The Builder used to scale such lines as "one pack per
# chamber" — or, where quantity counted packs, as N x packs — so x4 chambers
# bought four camera 2-packs (8 cameras) and four 100-packs of resistors.

CHAMBERS = (1, 4, 12)

# (quantity, shared_units, pack_size, packs bought at x1 / x4 / x12 chambers)
# for every pack line. Changing a pack or a quantity must change this table on
# purpose. pi-ui's builder-data tests pin the same numbers (frontend/packages/
# pi-ui, private monorepo). shared_units is the Pi case's share of the same
# packs, bought once: N chambers need quantity x N + shared_units units.
EXPECTED_PACKS = {
    "recommended": {
        "ESP32-WROOM-32 DevKit": (3, 0, 3, (1, 4, 12)),
        "IRLZ44N": (6, 0, 10, (1, 3, 8)),
        "100 Ohm Resistor": (6, 0, 100, (1, 1, 1)),
        "10K Ohm Resistor": (6, 0, 100, (1, 1, 1)),
        "Flyback Diode": (4, 0, 125, (1, 1, 1)),
        "2-pos 5.08 mm PCB Screw Terminals": (16, 0, 30, (1, 3, 7)),
        "Dupont Jumper Wires": (8, 0, 40, (1, 1, 3)),
        "DC Barrel Pigtail": (1, 0, 2, (1, 2, 6)),
        "ESP32-CAM": (1, 0, 2, (1, 2, 6)),
        "USB-A to USB-C Data Cable, 1 ft": (2, 0, 3, (1, 3, 8)),
        "USB-A to Micro-USB Data Cable": (1, 0, 2, (1, 2, 6)),
        "USB Wall Charger": (4, 0, 2, (2, 8, 24)),
        "18 AWG 2-Conductor": (20, 0, 100, (1, 1, 3)),
        "22 AWG Stranded Hookup": (2, 0, 10, (1, 1, 3)),
        "WAGO 221": (1, 0, 3, (1, 2, 4)),
        "Inline ATC/ATO Blade Fuse Holders": (2, 0, 10, (1, 1, 3)),
        "ATC Blade Fuse Assortment": (1, 0, 15, (1, 1, 1)),
        "Noctua NA-SEC3": (3, 0, 3, (1, 4, 12)),
        "Adhesive-Lined Heat Shrink": (15, 0, 400, (1, 1, 1)),
        "UV-Resistant Zip Ties": (25, 0, 400, (1, 1, 1)),
        "Zip Ties, 18": (3, 0, 100, (1, 1, 1)),
        "VELCRO ONE-WRAP": (2, 0, 12, (1, 1, 2)),
        "Rubber Grommet Kit": (1, 0, 20, (1, 1, 1)),
        "ruthex Heat-Set Insert Assortment": (12, 0, 50, (1, 1, 3)),
        "Heat-Set Inserts M2.5": (6, 4, 70, (1, 1, 2)),
        "M2.5 Socket Head Screw Kit": (6, 4, 40, (1, 1, 2)),
        "M3 x 6 mm Socket Head Screws": (22, 0, 100, (1, 1, 3)),
        "Socket Head Screw Kit M2.5-M8": (1, 0, 10, (1, 1, 2)),
        "M4 Socket Head Screw Kit": (12, 0, 38, (1, 2, 4)),
        "Lead-Free Rosin-Core Solder": (5, 0, 50, (1, 1, 2)),
    },
    "all_the_things": {
        "ESP32-WROOM-32 DevKit": (4, 0, 6, (1, 3, 8)),
        "IRLZ44N": (8, 0, 10, (1, 4, 10)),
        "100 Ohm Resistor": (8, 0, 100, (1, 1, 1)),
        "10K Ohm Resistor": (9, 0, 100, (1, 1, 2)),
        "Flyback Diode": (4, 0, 125, (1, 1, 1)),
        "2-pos 5.08 mm PCB Screw Terminals": (16, 0, 30, (1, 3, 7)),
        "Dupont Jumper Wires": (10, 0, 40, (1, 1, 3)),
        "DC Barrel Pigtail": (1, 0, 2, (1, 2, 6)),
        "ESP32-CAM": (2, 0, 2, (1, 4, 12)),
        "USB-A to USB-C Data Cable, 1 ft": (2, 0, 3, (1, 3, 8)),
        "USB-A to Micro-USB Data Cable": (2, 0, 2, (1, 4, 12)),
        "USB Wall Charger": (6, 0, 2, (3, 12, 36)),
        "Magnetic Door Contact": (1, 0, 2, (1, 2, 6)),
        "18 AWG 2-Conductor": (35, 0, 100, (1, 2, 5)),
        "22 AWG Stranded Hookup": (2, 0, 10, (1, 1, 3)),
        "22 AWG 4-Conductor": (12, 0, 50, (1, 1, 3)),
        "WAGO 221": (1, 0, 3, (1, 2, 4)),
        "Inline ATC/ATO Blade Fuse Holders": (2, 0, 10, (1, 1, 3)),
        "ATC Blade Fuse Assortment": (1, 0, 15, (1, 1, 1)),
        "Noctua NA-SEC3": (3, 0, 3, (1, 4, 12)),
        "Adhesive-Lined Heat Shrink": (25, 0, 400, (1, 1, 1)),
        "UV-Resistant Zip Ties": (25, 0, 400, (1, 1, 1)),
        "Zip Ties, 18": (3, 0, 100, (1, 1, 1)),
        "VELCRO ONE-WRAP": (2, 0, 12, (1, 1, 2)),
        "Rubber Grommet Kit": (1, 0, 20, (1, 1, 1)),
        "ruthex Heat-Set Insert Assortment": (36, 4, 100, (1, 2, 5)),
        "Heat-Set Inserts M2.5": (16, 4, 70, (1, 1, 3)),
        "M2.5 Socket Head Screw Kit": (12, 4, 40, (1, 2, 4)),
        "M3 x 6 mm Socket Head Screws": (36, 0, 100, (1, 2, 5)),
        "Socket Head Screw Kit M2.5-M8": (2, 0, 10, (1, 1, 3)),
        "M4 Socket Head Screw Kit": (12, 0, 38, (1, 2, 4)),
        "M4 x 8 mm Cup-Point Set Screws": (4, 0, 50, (1, 1, 1)),
        "Lead-Free Rosin-Core Solder": (7, 0, 50, (1, 1, 2)),
    },
    "bare_bones": {
        "USB Wall Charger": (1, 0, 2, (1, 2, 6)),
        "UV-Resistant Zip Ties": (25, 0, 400, (1, 1, 1)),
        "Rubber Grommet Kit": (1, 0, 20, (1, 1, 1)),
        "ruthex Heat-Set Inserts M3 x 5.7": (10, 4, 100, (1, 1, 2)),
        "Heat-Set Inserts M2.5": (6, 4, 70, (1, 1, 2)),
        "M2.5 Socket Head Screw Kit": (6, 4, 40, (1, 1, 2)),
        "M3 x 6 mm Socket Head Screws": (10, 0, 100, (1, 1, 2)),
    },
}

# parts_cost() at x1 / x4 / x12 chambers. x1 is what estimated_cost rounds;
# pi-ui's bomTotals() must return the same three figures for each tier.
EXPECTED_TOTALS = {
    "bare_bones": (290.90, 484.60, 1047.80),
    "recommended": (747.83, 1733.38, 4618.18),
    "all_the_things": (964.68, 2613.78, 7154.87),
}


def _pack_lines(tier: HardwareTier) -> list[Component]:
    return [c for c in tier.components if c.pack_price or c.pack_size]


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_pack_fields_come_together_and_price_one_unit(tier_id):
    """No legacy pack line: pack_price and pack_size are set together, and
    price_approx is the pack's own per-unit price (to the cent)."""
    for c in _pack_lines(_tier(tier_id)):
        assert c.pack_price and c.pack_size >= 2, f"{c.name}: pack_price without pack_size or vice versa"
        per_unit = usd(c.pack_price) / c.pack_size
        assert abs(usd(c.price_approx) - per_unit) <= 0.01, (
            f"{c.name}: price_approx {c.price_approx} is not {c.pack_price} / {c.pack_size}")


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_pack_named_lines_carry_their_pack_size(tier_id):
    """A line sold as an 'N-pack' / 'N-set' counts units, not packs."""
    for c in _tier(tier_id).components:
        m = re.search(r"(\d+)-(?:pack|set)\b", c.name)
        if m and not c.shared:
            assert c.pack_size == int(m.group(1)), f"{c.name}: pack_size {c.pack_size}"


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_every_pack_line_buys_whole_packs_per_chamber_count(tier_id):
    tier = _tier(tier_id)
    lines = {c.name: c for c in _pack_lines(tier)}
    expected = EXPECTED_PACKS[tier_id]
    assert len(lines) == len(expected), sorted(lines)
    for prefix, (quantity, pi_units, size, packs) in expected.items():
        c = next(c for name, c in lines.items() if name.startswith(prefix))
        assert (c.quantity, c.shared_units, c.pack_size) == (quantity, pi_units, size), c.name
        for n, want in zip(CHAMBERS, packs, strict=True):
            units = c.units(n)
            assert units == quantity * n + pi_units, c.name
            assert c.packs(n) == want == math.ceil(units / size), (c.name, n)
            assert (want - 1) * size < units <= want * size, (c.name, n)  # the fewest packs
            assert c.line_cost(n) == pytest.approx(want * usd(c.pack_price)), (c.name, n)


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_shared_lines_never_multiply(tier_id):
    for c in _tier(tier_id).components:
        if c.shared:
            for n in CHAMBERS:
                assert c.units(n) == c.quantity, c.name
                assert c.line_cost(n) == c.line_cost(), c.name


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_tier_totals_per_chamber_count(tier_id):
    tier = _tier(tier_id)
    got = tuple(round(tier.parts_cost(n), 2) for n in CHAMBERS)
    assert got == EXPECTED_TOTALS[tier_id]
    assert tier.parts_cost() == pytest.approx(sum(c.line_cost() for c in tier.components))


def test_pack_math_rounds_up_to_whole_packs():
    part = Component(name="x", role="", quantity=6, price_approx="$1", pack_price="$10",
                     pack_size=10, url="https://example.com", category="misc")
    assert [part.packs(n) for n in (1, 2, 3, 5)] == [1, 2, 2, 3]  # 6, 12, 18, 30 units
    assert part.line_cost(5) == 30
    exact = part.model_copy(update={"quantity": 5})
    assert [exact.packs(n) for n in (1, 2, 3)] == [1, 1, 2]  # 10 units fill one pack
    single = part.model_copy(update={"pack_price": "", "pack_size": 0})
    assert single.packs(4) == 0 and single.line_cost(4) == 24
    with pytest.raises(ValueError):
        part.line_cost(0)


def test_shared_units_are_bought_once_on_top_of_the_chambers():
    # The Pi case's 4 M2.5 inserts come out of the same 70-pack the chambers
    # use: N chambers need 6N + 4, never 10N.
    part = Component(name="x", role="", quantity=6, shared_units=4, price_approx="$0.13",
                     pack_price="$9", pack_size=70, url="https://example.com", category="hardware")
    assert [part.units(n) for n in (1, 2, 11, 12)] == [10, 16, 70, 76]
    assert [part.packs(n) for n in (1, 11, 12)] == [1, 1, 2]
    assert part.line_cost(12) == 18


def test_legacy_pack_price_without_size_keeps_one_pack_per_chamber():
    legacy = Component(name="x", role="", quantity=6, price_approx="$0.05", pack_price="$5.49",
                       url="https://example.com", category="misc")
    assert [legacy.packs(n) for n in (1, 4)] == [1, 4]
    assert legacy.line_cost(4) == pytest.approx(4 * 5.49)
    shared = legacy.model_copy(update={"shared": True})
    assert shared.packs(4) == 1 and shared.line_cost(4) == 5.49


# What a line counts when it is not whole pieces of the named part (2026-10
# browser audit: "18 AWG … 100 ft | ×420 · 5 packs of 100 · ~$0.26 ea" — 420
# what?). Every other line counts pieces ("").
EXPECTED_UNITS = {
    "18 AWG 2-Conductor": "ft",
    "22 AWG Stranded Hookup": "ft",
    "22 AWG 4-Conductor": "ft",
    "Lead-Free Rosin-Core Solder": "g",
    "VELCRO ONE-WRAP": "strap",
    "WAGO 221": "chamber set",
    "ATC Blade Fuse Assortment": "chamber set",
    "Dupont Jumper Wires": "M-F jumper",
    "Rubber Grommet Kit": "large grommet",
    "M2.5 Socket Head Screw Kit": "M2.5 x 6 screw",
    "M4 Socket Head Screw Kit": "fan-duct screw",
    # mixed kits counted in a different size per tier (their notes say which)
    "ruthex Heat-Set Insert Assortment": {"recommended": "M4 insert", "all_the_things": "M3 insert"},
    "Socket Head Screw Kit M2.5-M8": {"bare_bones": "", "recommended": "M5 x 16 screw",
                                      "all_the_things": "M5 x 16 screw"},
}


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_lines_bought_by_length_weight_or_kit_piece_say_what_they_count(tier_id):
    for c in _tier(tier_id).components:
        key = next((k for k in EXPECTED_UNITS if c.name.startswith(k)), None)
        want = EXPECTED_UNITS.get(key, "") if key else ""
        if isinstance(want, dict):
            want = want[tier_id]
        assert c.unit == want, (tier_id, c.name, c.unit)
        if c.unit:
            # only a pack line counts something other than the part itself
            assert c.pack_size and c.pack_price, c.name
            assert c.unit == c.unit.strip() and not c.unit.endswith("s"), c.name  # singular


def test_api_exposes_pack_size(client):
    for tier in TIERS:
        body = client.get(f"/api/builder/tiers/{tier.id}").json()
        assert [c["unit"] for c in body["components"]] == [c.unit for c in tier.components]
        assert [c["pack_size"] for c in body["components"]] == [c.pack_size for c in tier.components]
        assert [c["shared_units"] for c in body["components"]] == [c.shared_units for c in tier.components]
        assert [c["quantity"] for c in body["components"]] == [c.quantity for c in tier.components]


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


@pytest.mark.parametrize(
    "tier_id,nodes,cams",
    [("bare_bones", 1, 0), ("recommended", 3, 1), ("all_the_things", 4, 2)],
)
def test_every_board_has_usb_power_and_a_cable(tier_id, nodes, cams):
    # Quantities count units (cubes, cables, cameras), never packs.
    tier = _tier(tier_id)
    assert _qty(tier, r"USB Wall Charger") == nodes + cams
    assert _qty(tier, r"USB-A to USB-C") == nodes
    assert _qty(tier, r"USB-A to Micro-USB") == cams
    assert _qty(tier, r"^ESP32-CAM") == cams
    assert _qty(tier, r"^ESP32-WROOM-32") == nodes
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
    assert esp.quantity == 4, "4 node boards per chamber; the 6-pack leaves 2 spares"
    assert esp.pack_size == 6 and esp.packs() == 1
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
    assert _qty(tier, r"Micro-USB Data Cable, 6 ft") == cams
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
        cubes = _qty(tier, r"^USB Wall Charger")
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


# ── Kits and spools the chambers use up ─────────────────────────
# Every kit and spool used to be `shared` — bought once whatever the chamber
# count — although each chamber consumes from it, so a multi-chamber shopping
# list under-bought from ~3-4 chambers up: the WAGO assortment (3 x 221-413 +
# 3 x 221-415, one of each per chamber) stayed one kit at x4 and x12, the
# 100 M3 inserts of the ruthex assortment one kit for 12 All the Things
# chambers that press 436. Now such a line counts what ONE chamber takes, in
# whole packs, with the Pi case's share of the same pack as `shared_units`.

# Up to the Builder's chamber input's maximum (99), past each bulk pack's
# coverage (16 zip ties / heat-shrink, 20 grommets, 33 duct ties).
UNDER_BUY_CHAMBERS = (1, 2, 4, 6, 12, 16, 17, 21, 34, 99)
MODELS_README = REPO_ROOT / "models" / "README.md"
_PI_SIDE = ("Raspberry Pi", "microSD")

# What each fastener kit holds, keyed by the models/README.md shopping-list
# rows its sizes fill. A mixed kit's line counts ONE of these sizes (the one
# the chambers use up first); the checks below cover every size.
KIT_CONTENTS = {
    "ruthex Heat-Set Inserts M3 x 5.7": {"M3 × 5.7 insert": 100},
    "ruthex Heat-Set Insert Assortment": {
        "M3 × 5.7 insert": 100, "M4 × 8.1 insert": 50, "M5 × 9.5 insert": 50},
    "Heat-Set Inserts M2.5": {"M2.5 × 5.7 insert": 70},
    "M2.5 Socket Head Screw Kit": {
        "M2.5 × 6 SHCS": 40, "M2.5 × 8 SHCS (or pan head)": 25, "M2.5 × 10 SHCS": 20},
    "M3 x 6 mm Socket Head Screws": {"M3 × 6 SHCS": 100},
    "Socket Head Screw Kit M2.5-M8": {"M3 × 16 SHCS": 10, "M4 × 16 SHCS": 10, "M5 × 16 SHCS": 10},
    # fan_duct takes M4 x 30, x35 or x40 (models/README.md): 15 + 13 + 10.
    "M4 Socket Head Screw Kit": {"M4 × 25 SHCS": 15, "M4 × 35 SHCS / button head": 38},
    "M4 x 8 mm Cup-Point Set Screws": {"M4 × 8 set screw": 50},
}
# The scale's 4 DIN 125 washers come from the M4 kit's washer bag, whose count
# the listing does not pin.
_UNCOUNTED_ROWS = {"M4 washer, DIN 125"}

_BENCH_TOOLS = ("Breadboard",)
_COVERS_RE = re.compile(r"covers (\d+) chambers")


@functools.cache
def _fastener_use() -> dict[str, tuple[dict[str, int], dict[str, int]]]:
    """{tier id: ({row: units a chamber}, {row: pi_case units})} from the
    models/README.md insert + screw shopping list: tier total minus pi_case."""
    text = _read(MODELS_README)
    section = text[text.index("## Shopping list (inserts and screws)"):]
    pi_row = re.search(r"^\| `pi_case` \| ([^|]+) \| ([^|]+) \|", section, re.M)
    assert pi_row, "models/README.md shopping list has no pi_case row"
    pi: dict[str, int] = {}
    for column, kind in ((pi_row.group(1), "insert"), (pi_row.group(2), "SHCS")):
        for n, size, length in re.findall(r"(\d+) × (M[\d.]+)×([\d.]+)", column):
            pi[f"{size} × {length} {kind}"] = int(n)
    head = re.search(r"^\| Item \| One of each model \| (.+) \|$", section, re.M)
    assert head, "models/README.md has no per-tier totals table"
    names = [cell.strip() for cell in head.group(1).split("|")]
    assert names == [t.name for t in TIERS], names
    totals: dict[str, dict[str, int]] = {t.id: {} for t in TIERS}
    for line in section[head.end():].split("\n\n")[0].splitlines()[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        for tier, cell in zip(TIERS, cells[2:], strict=True):
            totals[tier.id][cells[0]] = 0 if cell == "—" else int(cell)
    assert set(pi) <= set(totals[TIERS[0].id]), sorted(set(pi) - set(totals[TIERS[0].id]))
    out = {}
    for tier in TIERS:
        rows = totals[tier.id]
        chamber = {row: n - pi.get(row, 0) for row, n in rows.items()}
        assert min(chamber.values()) >= 0, (tier.id, chamber)
        out[tier.id] = (chamber, {row: pi.get(row, 0) for row in rows})
    return out


def _kit_lines(tier: HardwareTier) -> list[tuple[Component, dict[str, int]]]:
    out = []
    for c in tier.components:
        key = next((k for k in KIT_CONTENTS if c.name.startswith(k)), None)
        if key:
            out.append((c, KIT_CONTENTS[key]))
    return out


def _kits_bought(c: Component, chambers: int) -> int:
    """Whole kits a line buys: its packs, or its units for a kit bought singly."""
    return c.packs(chambers) if c.pack_size else c.units(chambers)


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_fastener_kits_count_what_the_models_use(tier_id):
    """A per-chamber kit line counts one of its sizes exactly as the models
    use it: quantity = a chamber's units, shared_units = the Pi case's,
    pack_size = that size's count in the kit. A shared kit serves the Pi
    case alone."""
    tier = _tier(tier_id)
    chamber, pi = _fastener_use()[tier_id]
    covered = set()
    for c, contents in _kit_lines(tier):
        covered |= set(contents)
        if c.shared:
            assert all(chamber[row] == 0 for row in contents), (
                f"{c.name}: chambers use it up, so it cannot be bought once")
            continue
        counted = [row for row, per_kit in contents.items()
                   if (c.quantity, c.shared_units, c.pack_size) == (chamber[row], pi[row], per_kit)]
        assert counted, (f"{c.name}: quantity {c.quantity} / shared_units {c.shared_units} / "
                         f"pack_size {c.pack_size} match no size of models/README.md")
    needed = {row for row, n in chamber.items() if n + pi[row] > 0} - _UNCOUNTED_ROWS
    assert needed <= covered, f"{tier_id}: no BOM kit carries {sorted(needed - covered)}"


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_no_fastener_size_is_under_bought(tier_id):
    """Every insert and screw size the printed parts take, for N chambers +
    the Pi case, fits in the kits the line buys — counted per size, so a
    mixed kit's other sizes are checked too."""
    tier = _tier(tier_id)
    chamber, pi = _fastener_use()[tier_id]
    for n in UNDER_BUY_CHAMBERS:
        capacity: dict[str, int] = {}
        for c, contents in _kit_lines(tier):
            for row, per_kit in contents.items():
                capacity[row] = capacity.get(row, 0) + _kits_bought(c, n) * per_kit
        for row, have in capacity.items():
            need = chamber[row] * n + pi[row]
            assert need <= have, f"{tier_id} x{n}: {row} needs {need}, the kits hold {have}"


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_no_per_chamber_line_is_under_bought(tier_id):
    for c in _tier(tier_id).components:
        if c.shared or not c.pack_size:
            continue
        for n in UNDER_BUY_CHAMBERS:
            need = c.quantity * n + c.shared_units
            assert c.units(n) == need, (c.name, n)
            assert need <= c.packs(n) * c.pack_size, (c.name, n)


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_shared_units_only_on_per_chamber_pack_lines(tier_id):
    for c in _tier(tier_id).components:
        assert c.shared_units >= 0, c.name
        if c.shared_units:
            assert c.pack_size and not c.shared, c.name


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_pack_notes_state_how_many_chambers_one_pack_covers(tier_id):
    """A consumable pack that serves several chambers says how many, and the
    number is the pack math's (for a fastener kit: its tightest size)."""
    tier = _tier(tier_id)
    chamber, pi = _fastener_use()[tier_id]
    kits = {c.name: contents for c, contents in _kit_lines(tier)}
    for c in tier.components:
        if c.shared or not c.pack_size:
            continue
        covers = (c.pack_size - c.shared_units) // c.quantity
        stated = [int(n) for n in _COVERS_RE.findall(c.notes)]
        if c.category in ("wiring", "hardware") or c.name.startswith("Dupont"):
            if covers >= 2:
                assert stated, f"{tier_id}: {c.name} never says how many chambers one pack covers"
        assert all(s == covers for s in stated), (c.name, stated, covers)
        if c.name in kits:
            tightest = min((per_kit - pi[row]) // chamber[row]
                           for row, per_kit in kits[c.name].items() if chamber[row])
            assert tightest == covers, (c.name, tightest, covers)


# The bulk consumables (zip ties, heat-shrink, grommets, 18" duct ties) used
# to be `shared` because one pack covered the Builder's largest preset (12
# chambers) — but its chamber input takes up to 99, and from 17 chambers
# those lists under-bought (2026-10 browser audit, ×40 All the Things: one
# 400-pack of zip ties for ~1,000). Only what no chamber uses up is bought
# once.
@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_only_the_pi_side_and_bench_tools_are_bought_once(tier_id):
    tier = _tier(tier_id)
    chamber, _ = _fastener_use()[tier_id]
    kits = {c.name: contents for c, contents in _kit_lines(tier)}
    for c in tier.components:
        if not c.shared or c.name.startswith(_PI_SIDE + _BENCH_TOOLS):
            continue
        assert c.name in kits, f"{tier_id}: {c.name} is bought once — what stops N chambers using it up?"
        # a kit only the Pi case draws on
        assert all(chamber[row] == 0 for row in kits[c.name]), c.name
        assert "Pi side" in c.notes, c.name


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_bulk_consumables_count_what_one_chamber_takes(tier_id):
    tier = _tier(tier_id)
    fans = _qty(tier, r"^Noctua NF-A8")
    for c in tier.components:
        if c.name.startswith(("UV-Resistant Zip Ties", "Adhesive-Lined Heat Shrink", "Rubber Grommet Kit")):
            assert not c.shared and c.pack_size >= 20, c.name
        if c.name.startswith("Zip Ties, 18"):  # one per fan_duct
            assert (c.quantity, c.pack_size, c.shared) == (fans, 100, False), c.name
        if c.name.startswith("Rubber Grommet Kit"):  # one large grommet a chamber
            assert c.quantity == 1, c.name


@pytest.mark.parametrize("tier_id", ["recommended", "all_the_things"])
def test_wiring_consumables_follow_the_wiring_rows(tier_id):
    tier = _tier(tier_id)

    def line(prefix):
        return next(c for c in tier.components if c.name.startswith(prefix))

    # One M-F Dupont per J1 terminal an ESP32 drives: each wired gate + one GND
    # per switch board.
    j1 = [w for w in tier.wiring
          if w.from_device in ("ESP32 (Relay)", "ESP32 (Lighting)")
          and ("IRLZ44N" in w.to_device or "switch board" in w.to_device)]
    assert line("Dupont").quantity == len(j1)
    # One 221-413 + one 221-415 per chamber; the assortment holds 3 of each.
    wagos = {w.to_device for w in tier.wiring if w.to_device.startswith("WAGO 221")}
    assert wagos == {"WAGO 221-413", "WAGO 221-415"}
    wago = line("WAGO 221")
    assert wago.quantity == 1 and wago.pack_size == 3
    assert "3 each of 221-412, 221-413, 221-415 and 221-2401" in wago.notes
    # A fuse holder per branch, one fuse set (relay + lighting rating) per chamber.
    fuse_rows = [w for w in tier.wiring if w.to_device.startswith("Inline fuse")]
    assert line("Inline ATC/ATO").quantity == len(fuse_rows) == 2
    assert line("ATC Blade Fuse Assortment").quantity == 1
    # Two 12" straps per power_supply_mount, one PSU brick per chamber.
    assert line("VELCRO").quantity == 2 * _qty(tier, r"^12V Power Supply")


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
#   env name       SPOREPRINT_* that docker-compose.yml passes or install.sh sets,
#                  as a whole word (a prefix of a longer name does not count)
#   fragment       `_LON`, `WEATHER_` — a name cut short never passes, even
#                  where some file prints the same fragment
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
    if re.fullmatch(r"_\w*|\w*_", span):
        return "a fragment of a name — write the whole name"
    if m := re.fullmatch(r"(SPOREPRINT_[A-Z0-9_]+)(=\S+)?", span):
        whole = re.compile(rf"(?<![\w-]){re.escape(m.group(1))}(?![\w-])")
        return None if whole.search(f.compose_text) or whole.search(f.install) else (
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


@pytest.mark.parametrize("span,ok", [
    ("SPOREPRINT_WEATHER_LON", True),
    ("SPOREPRINT_WEATHER_LAT", True),
    ("_LON", False),            # what the weather step and the API message used to say
    ("_LAT", False),
    ("SPOREPRINT_WEATHER_", False),
    ("SPOREPRINT_WEATHER_LO", False),  # a prefix of a real name
    ("WEATHER_LON", False),     # only ever inside SPOREPRINT_WEATHER_LON
])
def test_code_span_check_rejects_name_fragments(span, ok):
    assert (_check_span(span, "", _facts()) is None) is ok


def test_weather_unavailable_message_names_both_env_names(client):
    """The API message spells out both names, so no doc or step can quote a
    `_LON`-style fragment back from the server's own text."""
    body = client.get("/api/weather/current").json()
    assert body["status"] == "unavailable"
    named = set(re.findall(r"SPOREPRINT_\w+", body["message"]))
    assert named == {"SPOREPRINT_WEATHER_LAT", "SPOREPRINT_WEATHER_LON"}, body["message"]
    assert not re.search(r"(?<!\w)_[A-Z]", body["message"]), body["message"]


# ── dashboard names in the steps ────────────────────────────────────────────
#
# Steps send the reader to Builder tabs and dashboard pages by name. Those
# names are checked against the dashboard this repo ships (ui/dist, the
# compiled pi-ui): the old "Builder page → ESP32 Firmware section", "Builder →
# 3D Models" and "Dashboard hardware panel" named things the page no longer has.

UI_DIST = REPO_ROOT / "ui" / "dist" / "assets"


@functools.cache
def _dashboard_names() -> tuple[frozenset[str], frozenset[str]]:
    """(Builder tab ids, sidebar page labels) from the compiled dashboard."""
    js = "\n".join(p.read_text(errors="replace") for p in UI_DIST.glob("*.js"))
    tabs = re.search(r'\["overview"((?:,"\w+")+)\]', js)
    assert tabs, "the Builder tab list is not in ui/dist — rebuilt with other tab ids?"
    pages = re.findall(r'\{to:"/[\w/-]*",label:"([^"]+)"\}', js)
    assert "Builder" in pages and "Hardware" in pages, pages
    return frozenset(["overview", *re.findall(r'"(\w+)"', tabs.group(1))]), frozenset(pages)


@pytest.mark.parametrize("tier_id", TIER_IDS)
def test_steps_name_real_builder_tabs_and_pages(tier_id):
    tabs, pages = _dashboard_names()
    for step in _tier(tier_id).setup_steps:
        prose = _CODE_RE.sub("", step)
        for m in re.finditer(r"Builder(?: page)? → ([\w ]+?)(?= tab\b|[;:,.)—]|$)", prose):
            assert m.group(1).lower() in tabs and prose[m.end():].startswith(" tab"), (
                f"{tier_id}: 'Builder → {m.group(1)}' is not a Builder tab ({sorted(tabs)})")
        for m in re.finditer(r"\b([A-Z]\w*(?: [A-Z]\w*)*) page\b", prose):
            assert m.group(1) in pages, f"{tier_id}: no {m.group(1)!r} page in the dashboard nav"
        for stale in ("ESP32 Firmware section", "3D Models", "hardware panel"):
            assert stale not in prose, f"{tier_id}: stale dashboard name {stale!r}"


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
