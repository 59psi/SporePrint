"""POST /api/hardware/nodes/{id}/command must not report "sent" for a
command that was never published (broker down, or cmd signing enforced
without SPOREPRINT_MQTT_HMAC_KEY)."""

import app.mqtt


def test_command_published_reports_sent(client, mock_mqtt):
    r = client.post("/api/hardware/nodes/relay-01/command",
                    json={"channel": "fae", "state": "on"})
    assert r.status_code == 200
    assert r.json() == {"status": "sent", "topic": "sporeprint/relay-01/cmd/fae"}
    assert mock_mqtt == [("sporeprint/relay-01/cmd/fae", {"state": "on"})]


def test_command_refused_by_publisher_is_503(client, mock_mqtt):
    mock_mqtt.mock.return_value = False
    r = client.post("/api/hardware/nodes/relay-01/command",
                    json={"channel": "exhaust", "state": "on"})
    assert r.status_code == 503
    assert "not published" in r.json()["detail"]


def test_command_with_no_broker_connection_is_503(client, monkeypatch):
    # Real mqtt_publish, no connected client (the lifespan MQTT task is stubbed).
    monkeypatch.setattr(app.mqtt, "_client", None)
    r = client.post("/api/hardware/nodes/relay-01/command",
                    json={"channel": "fae", "state": "off"})
    assert r.status_code == 503


def test_command_signing_enforced_without_key_is_503(client, monkeypatch, mock_mqtt_raw):
    # A connected broker, but a cloud-paired Pi with no HMAC key refuses to
    # ship the unsigned actuator frame.
    monkeypatch.setattr(app.mqtt.settings, "mqtt_hmac_key", "")
    monkeypatch.setattr(app.mqtt.settings, "mqtt_require_signing", "always")
    r = client.post("/api/hardware/nodes/relay-01/command",
                    json={"channel": "fae", "state": "on"})
    assert r.status_code == 503
    assert mock_mqtt_raw == []


def test_invalid_channel_still_400(client, mock_mqtt):
    r = client.post("/api/hardware/nodes/relay-01/command",
                    json={"channel": "../other", "state": "on"})
    assert r.status_code == 400
    assert mock_mqtt == []
