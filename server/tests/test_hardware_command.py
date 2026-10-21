"""POST /api/hardware/nodes/{id}/command must not report "sent" for a
command that was never published (broker down, or cmd signing enforced
without SPOREPRINT_MQTT_HMAC_KEY)."""

import pytest

import app.mqtt


def test_command_published_reports_sent(client, mock_mqtt):
    r = client.post("/api/hardware/nodes/relay-01/command",
                    json={"channel": "fae", "state": "on"})
    assert r.status_code == 200
    assert r.json() == {"status": "sent", "topic": "sporeprint/relay-01/cmd/fae"}
    assert mock_mqtt == [("sporeprint/relay-01/cmd/fae", {"state": "on"})]


@pytest.mark.parametrize("failure", ["publisher refused", "no broker", "signing without a key"])
def test_a_command_that_was_not_published_is_503(client, request, monkeypatch, failure):
    if failure == "publisher refused":
        request.getfixturevalue("mock_mqtt").mock.return_value = False
    elif failure == "no broker":
        # The real mqtt_publish, no connected client (the lifespan MQTT task is stubbed).
        monkeypatch.setattr(app.mqtt, "_client", None)
    else:
        # A connected broker, but a cloud-paired Pi with no HMAC key refuses
        # to ship the unsigned actuator frame.
        raw = request.getfixturevalue("mock_mqtt_raw")
        monkeypatch.setattr(app.mqtt.settings, "mqtt_hmac_key", "")
        monkeypatch.setattr(app.mqtt.settings, "mqtt_require_signing", "always")
    r = client.post("/api/hardware/nodes/relay-01/command", json={"channel": "fae", "state": "on"})
    assert r.status_code == 503
    assert "not published" in r.json()["detail"]
    if failure == "signing without a key":
        assert raw == []


def test_invalid_channel_still_400(client, mock_mqtt):
    r = client.post("/api/hardware/nodes/relay-01/command",
                    json={"channel": "../other", "state": "on"})
    assert r.status_code == 400
    assert mock_mqtt == []


def test_a_trailing_newline_never_reaches_a_topic(client, mock_mqtt):
    """A regex `$` also matches before a trailing newline, so "abc\\n" used to
    pass and publish sporeprint/abc\\n/cmd/fae: a topic the node never hears,
    reported as "sent"."""
    r = client.post("/api/hardware/nodes/abc%0A/command",
                    json={"channel": "fae", "state": "on"})
    assert r.status_code == 400
    r = client.post("/api/hardware/nodes/relay-01/command",
                    json={"channel": "fae\n", "state": "on"})
    assert r.status_code == 400
    r = client.post("/api/hardware/nodes/abc%0A/peripherals", json={"hx711": True})
    assert r.status_code == 400
    r = client.post("/api/hardware/claim", json={"node_id": "relay-01\n"})
    assert r.status_code == 400
    assert mock_mqtt == []
