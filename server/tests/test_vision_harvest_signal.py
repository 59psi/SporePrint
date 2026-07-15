"""Vision alerts the operator when fruiting slows — the harvest signal.

The spec: "cameras would monitor for contamination, fruiting, and alert when
fruiting SLOWS so you know about when to harvest." Contamination detection
already existed. This adds the harvest signal: the per-frame Claude read
(harvest_readiness / growth_rate) corroborated across recent frames, so a slowed
or ready fruit body pages the operator — without firing on a single noisy frame.
"""

from app.vision.service import harvest_signal


def _frame(readiness="not_ready", rate="expanding"):
    return {"harvest_readiness": readiness, "growth_rate": rate}


# ── only during fruiting ───────────────────────────────────────────────────


def test_no_signal_outside_fruiting():
    ripe = [_frame("overdue", "stalled")]
    for phase in ("substrate_colonization", "cold_storage", "agar", "complete"):
        assert harvest_signal(phase, ripe) == (False, None)


def test_no_signal_while_still_growing():
    frames = [_frame("not_ready", "expanding"), _frame("approaching", "expanding")]
    assert harvest_signal("fruiting", frames) == (False, None)


# ── the signal fires ───────────────────────────────────────────────────────


def test_overdue_fires_even_on_a_single_frame():
    """Overdue is unambiguous — don't wait for corroboration to lose the flush."""
    ok, reason = harvest_signal("fruiting", [_frame("overdue", "stalled")])
    assert ok and "overdue" in reason


def test_ready_fires_only_when_corroborated():
    # one 'ready' frame after an expanding one: could be a noisy read — hold.
    assert harvest_signal("fruiting", [_frame("approaching", "expanding"),
                                       _frame("ready", "slowing")]) == (False, None)
    # two mature frames in a row: real.
    ok, reason = harvest_signal("fruiting", [_frame("ready", "slowing"),
                                             _frame("ready", "slowing")])
    assert ok and reason


def test_slowed_growth_is_the_harvest_cue():
    ok, reason = harvest_signal("fruiting", [_frame("approaching", "slowing"),
                                             _frame("approaching", "stalled")])
    assert ok and "slowed" in reason


def test_primordia_counts_as_fruiting_for_this():
    ok, _ = harvest_signal("primordia_induction", [_frame("ready", "slowing"),
                                                   _frame("overdue", "stalled")])
    assert ok


def test_empty_history_is_safe():
    assert harvest_signal("fruiting", []) == (False, None)
