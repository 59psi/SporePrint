"""The Tapo dual-transport driver (KLAP on the LAN, TP-Link cloud login).

* Config: local transport by default, a pasted password trimmed, the dimmer
  and energy-meter flags read; a malformed email or a device ip that is no
  address is refused.
* A local Test handshakes with each plug and reports the ones that answered
  (an error only when none did). The KLAP derivation itself is pinned by the
  known-answer tests in test_integrations_tapo_klap_vectors.py.
* A cloud Test logs in and keeps the token.
* set_power / set_dim send set_device_info over an encrypted KLAP request.
"""

from __future__ import annotations

import httpx
import pytest

from app.integrations.tapo.config import TapoConfig
from app.integrations.tapo.driver import TapoDriver, TapoError
from tests._pi_c1_integrations import EMAIL, FakeKlapPlugs, route_httpx, tapo_cfg, tapo_ok


# ── Config ────────────────────────────────────────────────────────────


def test_config_defaults_to_local_and_reads_what_the_form_sends():
    assert TapoConfig().transport == "local"
    cfg = TapoConfig(email="b@example.com", password="  pw\n ",
                     devices=[{"ip": "10.0.0.30", "is_dimmer": True, "has_emeter": True}])
    assert cfg.password == "pw"
    assert (cfg.devices[0].is_dimmer, cfg.devices[0].has_emeter) == (True, True)


@pytest.mark.parametrize("fields,error", [
    ({"email": "bad-email"}, "@"),
    # urlparse accepts many odd strings; a blank host after parsing is refused.
    ({"devices": [{"ip": "/"}]}, "ip"),
], ids=["email", "device-ip"])
def test_config_refuses_what_the_driver_cannot_use(fields, error):
    with pytest.raises(ValueError, match=error):
        TapoConfig(**fields)


# ── Test ──────────────────────────────────────────────────────────────


async def test_local_test_reports_the_plugs_that_answered(monkeypatch):
    # Firmware that sets no session cookie still handshakes.
    plugs = FakeKlapPlugs(lambda host, body: tapo_ok(), down={"10.0.0.31"}, cookie=False)
    route_httpx(monkeypatch, plugs)
    drv = TapoDriver()
    await drv.configure(tapo_cfg("10.0.0.30", "10.0.0.31"))

    health = await drv.test_connection()
    assert health.state == "ok"
    assert (health.details["transport"], health.details["reachable"],
            health.details["total"]) == ("local", 1, 2)
    assert health.details["errors"][0].startswith("10.0.0.31: ")

    plugs.down.add("10.0.0.30")
    health = await drv.test_connection()
    assert health.state == "error"
    assert "10.0.0.30: " in health.last_error and "10.0.0.31: " in health.last_error


async def test_cloud_test_logs_in_and_keeps_the_token(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"result": {"token": "abc-123"}})

    route_httpx(monkeypatch, handler)
    drv = TapoDriver()
    await drv.configure(TapoConfig(transport="cloud", email=EMAIL, password="pw"))
    health = await drv.test_connection()
    assert health.state == "ok"
    assert health.details["transport"] == "cloud"
    assert drv._cloud_token == "abc-123"


# ── Write paths ──────────────────────────────────────────────────────


async def test_writes_send_set_device_info_over_an_encrypted_request(monkeypatch):
    plugs = FakeKlapPlugs(lambda host, body: tapo_ok())
    route_httpx(monkeypatch, plugs)
    drv = TapoDriver()
    await drv.configure(tapo_cfg("10.0.0.30", is_dimmer=True))

    assert await drv.set_power("10.0.0.30", True) == {"ip": "10.0.0.30", "state": "on"}
    assert await drv.set_dim("10.0.0.30", 30) == {"ip": "10.0.0.30", "percent": 30}
    # The fake plug decrypted each request under the session it handshook.
    assert plugs.calls == [
        ("10.0.0.30", {"method": "set_device_info", "params": {"device_on": True}}),
        ("10.0.0.30", {"method": "set_device_info", "params": {"brightness": 30}}),
    ]


async def test_a_plug_error_fails_the_write_and_an_expired_session_handshakes_again(monkeypatch):
    plugs = FakeKlapPlugs(lambda host, body: tapo_ok())
    route_httpx(monkeypatch, plugs)
    drv = TapoDriver()
    await drv.configure(tapo_cfg("10.0.0.30"))

    plugs.request_status = 500
    with pytest.raises(TapoError, match="HTTP 500"):
        await drv.set_power("10.0.0.30", False)
    assert "10.0.0.30" in drv._sessions  # a plug error is not a dead session

    plugs.request_status = 403
    with pytest.raises(TapoError, match="session expired"):
        await drv.set_power("10.0.0.30", False)
    assert "10.0.0.30" not in drv._sessions

    # A safety OFF retried after that goes out on a fresh handshake.
    plugs.request_status = None
    plugs.local.clear()
    assert await drv.set_power("10.0.0.30", False) == {"ip": "10.0.0.30", "state": "off"}
    assert plugs.local, "a new handshake1 was sent"
