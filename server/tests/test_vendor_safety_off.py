"""The vendor dispatcher's writable actions and the safety ceiling's OFFs stay
one table apart, never out of step.

A vendor added to VENDOR_ACTIONS with an on/off action but no OFF line here
gets no safety_max_on_seconds ceiling at all — only a log warning — so a rule
that looks bounded is not.
"""

import pytest

import app.automation.engine as engine
from app.integrations._actions import (
    ON_OFF_ACTIONS,
    VENDOR_ACTIONS,
    VENDOR_SAFETY_OFF,
    vendor_device_key,
    vendor_safety_off,
)


def test_every_on_off_vendor_has_a_safety_off():
    on_off = {slug for slug, actions in VENDOR_ACTIONS.items() if actions.keys() & ON_OFF_ACTIONS}
    assert set(VENDOR_SAFETY_OFF) == on_off
    # One copy of the table: the ceiling reads exactly what the dispatcher offers.
    assert engine._VENDOR_SAFETY_OFF is VENDOR_SAFETY_OFF


def test_each_safety_off_is_an_action_its_vendor_offers():
    for slug, (action, device_param, params) in VENDOR_SAFETY_OFF.items():
        assert action in VENDOR_ACTIONS[slug], slug
        assert action in ON_OFF_ACTIONS, slug
        assert device_param and params, slug


@pytest.mark.parametrize("slug,params", [
    ("kasa", {"on": True}),               # no device id
    ("kasa", {"ip": "", "on": True}),
    ("quest", {"humidity_pct": 55}),      # a vendor with no OFF
])
def test_a_device_the_ceiling_cannot_name_gets_no_key_and_no_off(slug, params):
    """No key: the rule is logged as unbounded rather than armed against nothing."""
    assert vendor_device_key(slug, params) is None
    assert vendor_safety_off(slug, params) is None
