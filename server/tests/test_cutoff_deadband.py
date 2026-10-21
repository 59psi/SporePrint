"""Heating, cooling and dehumidify cutoffs switch off a deadband inside the band.

The triggers switch on past the band's edge (temp > temp_max_f, ...). The
cutoffs used to switch off at that same edge, so a reading wandering around it
switched the plug on and off every few minutes: relay wear on every plug,
short-cycling on a compressor cooler or dehumidifier. They now switch off a
deadband inside the band (1 °F / 3 %RH, at most a quarter of the band).
"""

import random

from app.automation.engine import _profile_value, evaluate_rules
from app.automation.service import seed_builtin_rules
from app.automation.smart_plugs import register_plug
from app.automation.templates import BUILTIN_RULES
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.models import PhaseParams
from app.species.service import seed_builtins
from tests._timing import clock as _clock
from tests._timing import local

_NOON = local(12)


def _params(temp=(55.0, 65.0), humidity=(85.0, 92.0)) -> PhaseParams:
    return PhaseParams(
        temp_min_f=temp[0], temp_max_f=temp[1], humidity_min=humidity[0],
        humidity_max=humidity[1], co2_max_ppm=800, co2_tolerance="low",
        light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
        fae_mode="scheduled", expected_duration_days=(5, 10),
    )


def test_off_points_sit_a_deadband_inside_the_band():
    p = _params()
    assert _profile_value(p, "temp_heat_off_f") == 56.0
    assert _profile_value(p, "temp_cool_off_f") == 64.0
    assert _profile_value(p, "humidity_dehumidify_off") == 92.0 - 7.0 / 4  # a quarter of 85-92
    wide = _params(humidity=(70.0, 95.0))
    assert _profile_value(wide, "humidity_dehumidify_off") == 92.0
    narrow = _params(temp=(72.0, 75.0))  # the narrowest band in the library: 3 °F
    heat_off = _profile_value(narrow, "temp_heat_off_f")
    cool_off = _profile_value(narrow, "temp_cool_off_f")
    assert (heat_off, cool_off) == (72.75, 74.25)
    assert heat_off < cool_off  # the heater stops before the cooler would


def test_each_cutoff_names_its_off_point():
    rules = {r.name: r for r in BUILTIN_RULES}
    refs = {name: rules[name].condition.threshold.profile_ref
            for name in ("Heating Cutoff", "Cooling Cutoff", "Dehumidify Cutoff")}
    assert refs == {"Heating Cutoff": "temp_heat_off_f", "Cooling Cutoff": "temp_cool_off_f",
                    "Dehumidify Cutoff": "humidity_dehumidify_off"}
    # The triggers still fire past the band's own edge.
    assert rules["Cooling Trigger"].condition.threshold.profile_ref == "temp_max_f"
    assert rules["Heating Trigger"].condition.threshold.profile_ref == "temp_min_f"
    assert rules["Dehumidify"].condition.threshold.profile_ref == "humidity_max"


async def _fruiting_closet_with_a_cooler():
    await seed_builtins()
    await seed_builtin_rules()
    await register_plug(plug_id="plug-cooler", name="cooler", plug_type="tasmota",
                        mqtt_topic_prefix="tasmota/cooler", device_role="cooler")
    # blue oyster fruiting: 55-65 °F, so the cooler stops at 64 °F.
    await create_session(SessionCreate(name="bo", species_profile_id="blue_oyster",
                                       substrate="straw", current_phase="fruiting"))


def _powers(raw) -> list[str]:
    return [p for t, p in raw if t == "tasmota/cooler/cmnd/POWER"]


async def test_the_cooler_runs_through_the_deadband(mock_mqtt, mock_mqtt_raw, quiet_alerts):
    await _fruiting_closet_with_a_cooler()
    t = _NOON
    for temp, expected in ((65.4, ["ON"]),      # past the band: on
                           (64.8, []),          # back inside, within the deadband: keep cooling
                           (64.3, []),
                           (63.9, ["OFF"])):    # past the deadband: off
        mock_mqtt_raw.clear()
        with _clock(t):
            await evaluate_rules("climate-1", {"temp_f": temp, "humidity": 88})
        assert _powers(mock_mqtt_raw) == expected, temp
        t += 61


async def test_noise_at_the_band_edge_no_longer_short_cycles(mock_mqtt, mock_mqtt_raw, quiet_alerts):
    """An hour of 60 s frames from a closet that warms 0.06 °F/min with the
    cooler off and cools 0.25 °F/min with it on, ±0.1 °F of sensor noise, at
    the 65 °F edge. Switching off at the edge started the cooler about 11
    times an hour; switching off 1 °F inside gives each cycle a whole degree
    to warm back through."""
    await _fruiting_closet_with_a_cooler()
    rng = random.Random(7)
    temp, cooler_on, starts, t = 65.0, False, 0, _NOON
    off_gaps, last_off = [], None
    for minute in range(60):
        mock_mqtt_raw.clear()
        with _clock(t):
            await evaluate_rules("climate-1", {"temp_f": round(temp + rng.uniform(-0.1, 0.1), 2),
                                               "humidity": 88})
        for power in _powers(mock_mqtt_raw):
            if power == "ON" and not cooler_on:
                starts += 1
                if last_off is not None:
                    off_gaps.append(minute - last_off)
            elif power == "OFF" and cooler_on:
                last_off = minute
            cooler_on = power == "ON"
        temp += -0.25 if cooler_on else 0.06
        t += 60
    assert 1 <= starts <= 4, starts
    assert off_gaps and min(off_gaps) >= 10, off_gaps  # it rests while warming 1 °F
