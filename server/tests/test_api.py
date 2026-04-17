"""Integration tests — exercise the full HTTP → router → service → DB stack."""

import pytest


@pytest.fixture(autouse=True)
def _seed(client):
    """Ensure the client fixture runs (triggers lifespan seeding) for every test in this module."""


# ── Health ──────────────────────────────────────────────────────


def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "3.1.14"}


# ── Sessions ────────────────────────────────────────────────────


def test_list_sessions_empty(client):
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert r.json() == []


def test_create_and_get_session(client):
    r = client.post("/api/sessions", json={
        "name": "API Test Grow",
        "species_profile_id": "blue_oyster",
    })
    assert r.status_code == 200
    session = r.json()
    assert session["name"] == "API Test Grow"
    assert session["status"] == "active"
    assert "id" in session

    r2 = client.get(f"/api/sessions/{session['id']}")
    assert r2.status_code == 200
    assert r2.json()["name"] == "API Test Grow"


def test_session_not_found(client):
    r = client.get("/api/sessions/99999")
    assert r.status_code == 404


def test_session_lifecycle_via_api(client):
    # Create
    r = client.post("/api/sessions", json={
        "name": "Lifecycle Test",
        "species_profile_id": "blue_oyster",
    })
    sid = r.json()["id"]

    # Advance phase
    r = client.post(f"/api/sessions/{sid}/phase", json={"phase": "fruiting"})
    assert r.status_code == 200
    assert r.json()["current_phase"] == "fruiting"

    # Add note
    r = client.post(f"/api/sessions/{sid}/note", json={"text": "Pins forming"})
    assert r.status_code == 200

    # Add harvest
    r = client.post(f"/api/sessions/{sid}/harvest", json={
        "flush_number": 1, "wet_weight_g": 150.0, "dry_weight_g": 15.0,
    })
    assert r.status_code == 200

    # Complete
    r = client.post(f"/api/sessions/{sid}/complete", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["total_wet_yield_g"] == 150.0

    # Events should have full history
    r = client.get(f"/api/sessions/{sid}/events")
    types = [e["type"] for e in r.json()]
    assert "session_created" in types
    assert "phase_change" in types
    assert "harvest" in types


# ── Species ─────────────────────────────────────────────────────


def test_list_species_after_seed(client):
    r = client.get("/api/species")
    assert r.status_code == 200
    profiles = r.json()
    assert len(profiles) >= 10
    names = [p["common_name"] for p in profiles]
    assert "Blue Oyster" in names


def test_get_species_profile(client):
    r = client.get("/api/species/blue_oyster")
    assert r.status_code == 200
    profile = r.json()
    assert profile["category"] == "gourmet"
    assert "phases" in profile
    assert "fruiting" in profile["phases"]


# ── Automation ──────────────────────────────────────────────────


def test_list_automation_rules(client):
    r = client.get("/api/automation/rules")
    assert r.status_code == 200
    rules = r.json()
    assert len(rules) > 0
    assert any(rule["name"] == "Humidity Boost" for rule in rules)


def test_create_and_toggle_rule(client):
    rule = {
        "name": "Test Rule",
        "description": "A test rule",
        "enabled": True,
        "priority": 1,
        "condition": {"type": "threshold", "threshold": {"sensor": "temp_f", "operator": "gt", "value": 80}},
        "action": {"target": "relay-01", "state": "on"},
        "cooldown_seconds": 60,
    }
    r = client.post("/api/automation/rules", json=rule)
    assert r.status_code == 200
    rule_id = r.json()["id"]

    r = client.patch(f"/api/automation/rules/{rule_id}/toggle")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


# ── Hardware ────────────────────────────────────────────────────


def test_list_hardware_nodes_empty(client):
    r = client.get("/api/hardware/nodes")
    assert r.status_code == 200
    assert r.json() == []


# ── Vision ──────────────────────────────────────────────────────


def test_list_vision_frames_empty(client):
    r = client.get("/api/vision/frames")
    assert r.status_code == 200
    assert r.json() == []


# ── Telemetry ───────────────────────────────────────────────────


def test_telemetry_ingest_and_query(client):
    r = client.post("/api/telemetry/ingest", json={
        "node_id": "test-node",
        "temp_f": 74.5,
        "humidity": 88.0,
        "co2_ppm": 650,
    })
    assert r.status_code == 200

    r = client.get("/api/telemetry/latest")
    assert r.status_code == 200
    readings = r.json()
    sensors = {row["sensor"] for row in readings}
    assert "temp_f" in sensors
    assert "humidity" in sensors


def test_telemetry_history_with_resolution(client):
    # Ingest readings across two 5-minute buckets (use non-zero timestamps)
    for i in range(6):
        client.post("/api/telemetry/ingest", json={
            "node_id": "test-node",
            "ts": 1000.0 + i * 100,
            "temp_f": 70.0 + i,
        })

    r = client.get("/api/telemetry/history", params={
        "node_id": "test-node",
        "sensor": "temp_f",
        "from_ts": 1000.0,
        "to_ts": 1600.0,
        "resolution": "5min",
    })
    assert r.status_code == 200
    data = r.json()
    # 300s buckets: 1000,1100 -> 900; 1200,1300,1400 -> 1200; 1500 -> 1500
    assert len(data) == 3


# ── Transcripts ─────────────────────────────────────────────────


def test_transcript_export(client):
    # Create a session first
    r = client.post("/api/sessions", json={
        "name": "Transcript API Test",
        "species_profile_id": "blue_oyster",
    })
    sid = r.json()["id"]

    # JSON export
    r = client.get(f"/api/transcript/sessions/{sid}/transcript", params={"format": "json"})
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == "1.0"
    assert data["session"]["name"] == "Transcript API Test"

    # Markdown export
    r = client.get(f"/api/transcript/sessions/{sid}/transcript", params={"format": "markdown"})
    assert r.status_code == 200
    assert "# Session: Transcript API Test" in r.text
