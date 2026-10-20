import pytest
import qrcode

from app.config import settings
from app.labels.router import DEFAULT_UI_ORIGIN, label_url


def test_qr_session_returns_png(client):
    """QR code for a session should return a valid PNG image."""
    resp = client.get("/api/labels/qr", params={"type": "session", "id": 1, "size": 150})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:4] == b"\x89PNG"


def test_qr_culture_returns_png(client):
    """QR code for a culture should return a valid PNG image."""
    resp = client.get("/api/labels/qr", params={"type": "culture", "id": 42, "size": 200})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:4] == b"\x89PNG"


def test_qr_invalid_type_returns_400(client):
    """Invalid type parameter should return 400."""
    resp = client.get("/api/labels/qr", params={"type": "invalid", "id": 1})
    assert resp.status_code == 400


# ── labels must encode a reachable UI URL ───────────────────────────────


@pytest.fixture()
def encoded(monkeypatch):
    """Capture the data each generated QR code encodes."""
    seen: list[str] = []
    real_add_data = qrcode.QRCode.add_data

    def _spy(self, data, *args, **kwargs):
        seen.append(data)
        return real_add_data(self, data, *args, **kwargs)

    monkeypatch.setattr(qrcode.QRCode, "add_data", _spy)
    return seen


def test_default_label_points_at_published_ui_port_and_real_route(client, encoded):
    client.get("/api/labels/qr", params={"type": "session", "id": 12})
    assert encoded == [f"{DEFAULT_UI_ORIGIN}/sessions?id=12"]
    assert DEFAULT_UI_ORIGIN == "http://sporeprint.local:3001"


def test_label_uses_the_origin_the_ui_was_reached_on(client, encoded):
    client.get(
        "/api/labels/qr", params={"type": "culture", "id": 7},
        headers={"Referer": "http://192.168.1.50:3001/cultures"},
    )
    assert encoded == ["http://192.168.1.50:3001/cultures?id=7"]


def test_explicit_base_url_wins(client, encoded):
    client.get(
        "/api/labels/qr",
        params={"type": "session", "id": 3, "base_url": "https://pi.lan:8443/ignored/path"},
        headers={"Referer": "http://192.168.1.50:3001/sessions"},
    )
    assert encoded == ["https://pi.lan:8443/sessions?id=3"]


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "not a url", "ftp://x/y", "",
                                 "http://[unbalanced"])
def test_invalid_origins_fall_back_to_default(bad):
    assert label_url("session", 1, bad) == f"{DEFAULT_UI_ORIGIN}/sessions?id=1"


# ── SPOREPRINT_PUBLIC_UI_URL is the label URL when the request names none ──
# The setting existed for exactly this (sporeprint.local does not resolve on
# every network or phone) but labels ignored it. A label URL typed into the
# browser, or fetched by a script, carries no Origin or Referer.

def test_a_request_with_no_origin_uses_the_public_ui_url(client, encoded, monkeypatch):
    monkeypatch.setattr(settings, "public_ui_url", "http://192.168.1.20:3001/")
    client.get("/api/labels/qr", params={"type": "session", "id": 5})
    assert encoded == ["http://192.168.1.20:3001/sessions?id=5"]


def test_the_page_that_asked_still_wins_over_the_setting(client, encoded, monkeypatch):
    monkeypatch.setattr(settings, "public_ui_url", "http://192.168.1.20:3001")
    client.get("/api/labels/qr", params={"type": "culture", "id": 2},
               headers={"Referer": "http://pi.lan:3001/cultures"})
    assert encoded == ["http://pi.lan:3001/cultures?id=2"]


@pytest.mark.parametrize("setting", ["", "not a url", "http://["])
def test_an_unusable_public_ui_url_falls_back_to_the_default(setting, monkeypatch):
    monkeypatch.setattr(settings, "public_ui_url", setting)
    assert label_url("session", 9) == f"{DEFAULT_UI_ORIGIN}/sessions?id=9"


def test_a_malformed_referer_is_ignored_not_a_500(client, encoded):
    r = client.get("/api/labels/qr", params={"type": "session", "id": 4},
                   headers={"Referer": "http://[oops"})
    assert r.status_code == 200
    assert encoded == [f"{DEFAULT_UI_ORIGIN}/sessions?id=4"]
