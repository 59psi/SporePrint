"""How the vendor-action dispatcher reads a payload and reports failures.

* Every bool / number parameter is parsed the way its annotation says, so a
  text field ("false", "50") reaches the device as a real value. Agrowtek's
  ``value: float | bool`` used to get the string itself — a controller that
  treats any non-empty string as true switched ON when asked for OFF.
* A caller's mistake (a missing parameter, a value the parameter cannot
  take) is a 400; a vendor's fault (an unreadable reply) is a 502. They used
  to be the other way round in places. The LAN actions route and the cloud's
  vendor_action proxy answer a missing parameter alike: a 400 naming it.
"""

from __future__ import annotations

import importlib

import httpx
import pytest
from fastapi import HTTPException

from app.cloud import integrations_proxy
from app.config import settings
from app.integrations import _actions, _registry
from tests._fakes import RecordingSio

fluence_mod = importlib.import_module("app.integrations.fluence.driver")
fohse_mod = importlib.import_module("app.integrations.fohse.driver")


@pytest.mark.parametrize("raw,wire", [
    ("false", False), ("off", False), ("true", True), (True, True),
    ("0", 0.0), ("50", 50.0), (75, 75.0), (0.5, 0.5),
])
async def test_agrowtek_value_reaches_the_controller_parsed(agrowtek_wire, raw, wire):
    await _actions.dispatch("agrowtek", "set_output", {"output_id": "3", "value": raw})
    url, body = agrowtek_wire[-1]
    assert url == "http://10.0.0.30/api/outputs/3"
    assert body == {"value": wire} and type(body["value"]) is type(wire)


@pytest.mark.parametrize("raw", ["abc", None, "", "nan"])
async def test_agrowtek_value_it_cannot_read_is_a_400(agrowtek_wire, raw):
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch("agrowtek", "set_output", {"output_id": "3", "value": raw})
    assert exc.value.status_code == 400
    assert "value must be a number or a boolean" in exc.value.detail
    assert agrowtek_wire == [], "nothing may be sent on a value the device can't take"


async def test_a_number_sent_as_text_is_parsed(kasa_wire):
    await _actions.dispatch("kasa", "set_dim", {"ip": "10.0.0.20", "percent": "50"})
    assert kasa_wire[-1] == ("10.0.0.20", {"smartlife.iot.dimmer": {"set_brightness": {"brightness": 50}}})


@pytest.mark.parametrize("percent", ["half", "50.5", None])
async def test_a_percent_it_cannot_read_is_a_400(kasa_wire, percent):
    # "50" used to reach `0 <= percent` as a string: a TypeError, reported
    # as a 502 vendor failure.
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch("kasa", "set_dim", {"ip": "10.0.0.20", "percent": percent})
    assert exc.value.status_code == 400
    assert kasa_wire == []


async def test_a_missing_parameter_is_a_400_not_a_vendor_failure(kasa_wire):
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch("kasa", "set_power", {"on": False})
    assert exc.value.status_code == 400
    assert "'ip'" in exc.value.detail
    assert kasa_wire == []


def test_the_actions_route_names_a_missing_parameter_with_a_400(client, kasa_wire):
    r = client.post("/api/integrations/kasa/actions/set_power", json={"on": False})
    assert r.status_code == 400
    assert "'ip'" in r.json()["detail"]
    r = client.post("/api/integrations/kasa/actions/set_power", json={"ip": "10.0.0.20"})
    assert r.status_code == 400
    assert "'on'" in r.json()["detail"]
    assert kasa_wire == []


async def test_the_cloud_proxy_names_a_missing_parameter_with_a_400(monkeypatch, kasa_wire):
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", False)

    sio = RecordingSio()
    await integrations_proxy.handle_request(sio, {
        "id": "va-1", "action": "vendor_action", "slug": "kasa",
        "payload": {"action": "set_power", "on": False},
    })
    ((_, reply),) = sio.events
    assert reply["success"] is False
    assert reply["status"] == 400
    assert "'ip'" in reply["error"]
    assert kasa_wire == []


def test_action_params_are_what_the_driver_gets():
    assert _actions.action_params(
        "kasa", "set_power", {"ip": "10.0.0.20", "on": "off", "extra": 1},
    ) == {"ip": "10.0.0.20", "on": False}


@pytest.mark.parametrize("module,cls,cfg_cls", [
    (fluence_mod, "FluenceDriver", "FluenceConfig"),
    (fohse_mod, "FohseDriver", "FohseConfig"),
])
async def test_a_vendor_reply_that_is_not_json_is_a_502(monkeypatch, module, cls, cfg_cls):
    # json.JSONDecodeError is a ValueError, which the dispatcher maps to 400
    # ("your request was wrong") — for what is the vendor's fault.
    drv = getattr(module, cls)()
    await drv.configure(getattr(module, cfg_cls)(email="a@b.co", password="pw"))
    monkeypatch.setattr(_registry, "registered_drivers", lambda: {drv.name: drv})

    async def html(self, url, **kwargs):
        return httpx.Response(200, text="<html>maintenance</html>")

    monkeypatch.setattr(httpx.AsyncClient, "post", html)
    monkeypatch.setattr(httpx.AsyncClient, "request", html, raising=False)
    monkeypatch.setattr(httpx.AsyncClient, "put", html)
    with pytest.raises(HTTPException) as exc:
        await _actions.dispatch(drv.name, "set_dim", {"fixture_id": "f1", "percent": 40})
    assert exc.value.status_code == 502
