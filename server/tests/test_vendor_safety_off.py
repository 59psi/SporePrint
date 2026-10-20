"""The vendor dispatcher's writable actions and the safety ceiling's OFFs stay
one table apart, never out of step.

A vendor added to VENDOR_ACTIONS with an on/off action but no OFF line here
gets no safety_max_on_seconds ceiling at all — only a log warning — so a rule
that looks bounded is not.
"""

import app.automation.engine as engine
from app.integrations._actions import (
    LAX_BOOL,
    ON_OFF_ACTIONS,
    VENDOR_ACTIONS,
    VENDOR_SAFETY_OFF,
)


def test_every_on_off_vendor_has_a_safety_off():
    on_off = {slug for slug, actions in VENDOR_ACTIONS.items() if actions.keys() & ON_OFF_ACTIONS}
    assert set(VENDOR_SAFETY_OFF) == on_off


def test_each_safety_off_is_an_action_its_vendor_offers():
    for slug, (action, device_param, params) in VENDOR_SAFETY_OFF.items():
        assert action in VENDOR_ACTIONS[slug], slug
        assert action in ON_OFF_ACTIONS, slug
        assert device_param and params, slug


def test_the_engine_reads_the_dispatchers_tables():
    """One copy of the OFF table and of the lax-bool parse: the ceiling reads
    a vendor rule's on/off exactly as the device is switched."""
    assert engine._VENDOR_SAFETY_OFF is VENDOR_SAFETY_OFF
    assert engine._vendor_actions.LAX_BOOL is LAX_BOOL
