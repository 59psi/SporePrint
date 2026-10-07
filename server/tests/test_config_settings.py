"""Settings that other modules read defensively via getattr(settings, ...).

vision/service and cloud/integrations_proxy were written against fields that
did not exist yet, so their env vars silently did nothing. These pin the
fields, their defaults, and the SPOREPRINT_* env names operators set.

Also: an env file with keys that are not settings, or a blank value for a
non-str setting, must not keep the server from booting.
"""

import pytest
from pydantic import ValidationError

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


def test_server_env_with_non_setting_keys_still_boots(tmp_path):
    """Bare metal reads server/.env. A copy of the repo-root .env carries TZ,
    FORWARDED_ALLOW_IPS and compose-only SPOREPRINT_* keys; an unknown key
    used to be 'Extra inputs are not permitted' and the server never booted."""
    env = tmp_path / ".env"
    env.write_text(
        "TZ=America/Los_Angeles\n"
        "FORWARDED_ALLOW_IPS=172.31.253.2\n"
        "SPOREPRINT_MQTT_3P_PASSWORD=plug-secret\n"
        "SPOREPRINT_SOME_FUTURE_KEY=1\n"
        "SPOREPRINT_NTFY_TOPIC=closet\n"
    )
    s = Settings(_env_file=str(env))
    assert s.ntfy_topic == "closet"
    assert not hasattr(s, "tz")
    assert not hasattr(s, "mqtt_3p_password")


def test_blank_non_str_setting_means_its_default(tmp_path, monkeypatch):
    """`SPOREPRINT_PORT=` (a key kept but emptied) used to fail int/bool/
    Literal validation and crash-loop the server at boot."""
    monkeypatch.delenv("SPOREPRINT_ALLOW_UNAUTHENTICATED", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "SPOREPRINT_PORT=\n"
        "SPOREPRINT_ALLOW_UNAUTHENTICATED=\n"
        "SPOREPRINT_MQTT_REQUIRE_SIGNING=\n"
        "SPOREPRINT_VISION_AUTO_INTERVAL_MIN=  \n"
    )
    monkeypatch.setenv("SPOREPRINT_MQTT_PORT", "")
    s = Settings(_env_file=str(env))
    assert s.port == 8000
    assert s.mqtt_port == 1883
    assert s.allow_unauthenticated is False      # the secure default
    assert s.mqtt_require_signing == "auto"
    assert s.vision_auto_interval_min == 360


def test_blank_str_setting_stays_blank(monkeypatch):
    # An empty ntfy URL disables notifications (notifications/service.py), so
    # blank strings keep their meaning — only non-str fields fall back.
    monkeypatch.setenv("SPOREPRINT_NTFY_URL", "")
    monkeypatch.setenv("SPOREPRINT_ALLOWED_HOSTS", "")
    s = Settings(_env_file=None)
    assert s.ntfy_url == ""
    assert s.allowed_hosts == ""


def test_a_malformed_non_blank_value_still_fails_loudly(monkeypatch):
    monkeypatch.setenv("SPOREPRINT_PORT", "eighty")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_signed_integrations_strict_mode_follows_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", True)
    assert integrations_proxy._require_signed_setting() is True
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", False)
    assert integrations_proxy._require_signed_setting() is False
