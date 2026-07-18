"""Stage-aware SAFETY alerts are always-on (GAP V5-1).

Safety DETECTION must fire regardless of rule state: a reading that drifts
outside the active stage range (but under the firmware absolute limit) has to
page the operator even when the operator has paused automation or disabled
every rule. Before this fix the ``_check_safety_thresholds`` call sat AFTER the
``if _paused: return`` and ``if not rules: return`` early returns in
``evaluate_rules`` — so pausing automation, or having zero enabled rules,
silently muted the "closet is on fire" alert on every channel.

These tests pin: with an active session in a phase that has a temperature band,
an out-of-stage-range emergency reading still emits the safety alert while the
engine is paused, and (separately) while there are zero enabled rules.
"""

import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
from app.automation.engine import evaluate_rules, load_rules, set_paused
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.service import seed_builtins


@pytest.fixture(autouse=True)
def _reset_pause_state():
    """Contain the pause flag within this module (conftest predates _paused)."""
    engine._paused = False
    engine._pause_loaded = False
    yield
    engine._paused = False
    engine._pause_loaded = False


@pytest.fixture()
def spy_alerts(monkeypatch):
    """Record every safety-alert emission without touching ntfy or the cloud.

    Returns a dict with 'critical' and 'forward' call lists. ``notify_critical``
    is bound into the engine namespace at import; ``forward_event`` is imported
    lazily from cloud.service inside _check_safety_thresholds.
    """
    critical: list[tuple] = []
    forward: list[tuple] = []

    async def _fake_critical(title, message, tags=None):
        critical.append((title, message, tags))

    async def _fake_forward(event_type, data):
        forward.append((event_type, data))

    monkeypatch.setattr(engine, "notify_critical", _fake_critical)
    monkeypatch.setattr(cloud_service, "forward_event", _fake_forward)
    return {"critical": critical, "forward": forward}


async def _seed_session_in_a_phase_with_a_temp_band():
    """Active session on a real profile; substrate_colonization = temp 75-80 F."""
    await seed_builtins()
    await create_session(SessionCreate(
        name="safety-always-on",
        species_profile_id="cubensis_golden_teacher",
        substrate="CVG",
        current_phase="substrate_colonization",
    ))


# 120 F is well past the 80 F ceiling + 5 F emergency margin → emergency alert.
_EMERGENCY_HOT = {"temp_f": 120}


async def test_safety_alert_still_fires_while_paused(spy_alerts):
    await _seed_session_in_a_phase_with_a_temp_band()

    await set_paused(True)
    await evaluate_rules("relay-01", _EMERGENCY_HOT)

    assert spy_alerts["critical"], "paused engine must still emit the safety alert"
    assert any(e == "temperature_alert" for e, _ in spy_alerts["forward"]), \
        "paused engine must still forward the safety event to the cloud"


async def test_safety_alert_still_fires_with_zero_enabled_rules(spy_alerts):
    await _seed_session_in_a_phase_with_a_temp_band()

    # No rules were created/seeded, so the engine has nothing to actuate.
    assert await load_rules() == [], "precondition: no enabled automation rules"

    await evaluate_rules("relay-01", _EMERGENCY_HOT)

    assert spy_alerts["critical"], "no-rules engine must still emit the safety alert"
    assert any(e == "temperature_alert" for e, _ in spy_alerts["forward"]), \
        "no-rules engine must still forward the safety event to the cloud"


# ── cold_storage humidity false-alarm (regression) ─────────────────────────
#
# cold_storage runs on _cold_storage_params() (humidity_min=80, humidity_max=95)
# but a fridge idles at a normal ~45% RH by design — humidity there is
# incidental, not chamber-driven. The safety monitor MUST NOT page a
# low-humidity emergency every telemetry frame in that phase. The gate is the
# PhaseParams.humidity_driven flag (False only for cold_storage), NOT fae_mode:
# both cold_storage AND substrate_colonization have fae_mode="none", yet
# colonization DOES actively drive humidity and must still page on a crash.

async def _seed_session_in_phase(phase: str):
    await seed_builtins()
    await create_session(SessionCreate(
        name=f"phase-{phase}",
        species_profile_id="cubensis_golden_teacher",
        substrate="CVG",
        current_phase=phase,
    ))


async def test_cold_storage_normal_fridge_rh_does_not_page(spy_alerts):
    """A fridge at ~45% RH and 38 F (both in-spec for cold storage) is silent."""
    await _seed_session_in_phase("cold_storage")

    # 38 F is inside 35-40; 45% RH is below the incidental 80 floor but the
    # phase does not drive humidity, so no humidity emergency may fire.
    await evaluate_rules("node-fridge-1", {"temp_f": 38, "humidity": 45})

    assert not any(e in ("humidity_alert", "humidity_warning")
                   for e, _ in spy_alerts["forward"]), \
        "cold storage must not page on a fridge's normal (undriven) low humidity"
    assert spy_alerts["critical"] == [], \
        "cold storage at spec temp + normal RH must emit no critical alert"


async def test_humidity_driven_phase_still_pages_on_low_rh(spy_alerts):
    """Colonization drives humidity (humidity_min=70) yet has fae_mode='none' —
    a 45% RH crash there MUST still page. This proves the fix keys on
    humidity_driven, not on the fae_mode gate that would wrongly mute it."""
    await _seed_session_in_phase("substrate_colonization")

    # 77 F is inside the 75-80 band (no temp alert); 45% RH is far below
    # humidity_min 70 minus the 8-point emergency margin → emergency low.
    await evaluate_rules("node-relay-1", {"temp_f": 77, "humidity": 45})

    assert any(e == "humidity_alert" for e, _ in spy_alerts["forward"]), \
        "a humidity-driven phase must still page on a low-RH crash"
    assert spy_alerts["critical"], \
        "a low-RH crash in a driven phase must emit a critical alert"
