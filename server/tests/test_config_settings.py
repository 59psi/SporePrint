"""Settings that other modules read defensively via getattr(settings, ...).

vision/service and cloud/integrations_proxy were written against fields that
did not exist yet, so their env vars silently did nothing. These pin the
fields, their defaults, and the SPOREPRINT_* env names operators set.
"""

from app.cloud import integrations_proxy
from app.config import Settings, settings
from app.vision import service as vision_service


def test_defaults_match_the_documented_behaviour():
    s = Settings()
    assert s.vision_auto_interval_min == 360          # spec §6: every 6 h
    assert s.cloud_require_signed_integrations is False
    assert s.public_ui_url == "http://sporeprint.local:3001"


def test_env_vars_reach_the_new_settings(monkeypatch):
    monkeypatch.setenv("SPOREPRINT_VISION_AUTO_INTERVAL_MIN", "30")
    monkeypatch.setenv("SPOREPRINT_CLOUD_REQUIRE_SIGNED_INTEGRATIONS", "true")
    monkeypatch.setenv("SPOREPRINT_PUBLIC_UI_URL", "http://192.168.1.20:3001")
    s = Settings()
    assert s.vision_auto_interval_min == 30
    assert s.cloud_require_signed_integrations is True
    assert s.public_ui_url == "http://192.168.1.20:3001"


def test_every_getattr_reader_resolves_a_real_field():
    for name in ("vision_auto_interval_min", "cloud_require_signed_integrations"):
        assert name in Settings.model_fields, name


def test_vision_cadence_follows_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "vision_auto_interval_min", 45)
    assert vision_service._auto_analysis_interval_seconds() == 45 * 60
    monkeypatch.setattr(settings, "vision_auto_interval_min", 0)
    assert vision_service._auto_analysis_interval_seconds() == 6 * 3600


def test_signed_integrations_strict_mode_follows_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", True)
    assert integrations_proxy._require_signed_setting() is True
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", False)
    assert integrations_proxy._require_signed_setting() is False
