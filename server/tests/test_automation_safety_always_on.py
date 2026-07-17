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
