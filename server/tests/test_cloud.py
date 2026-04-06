"""Tests for cloud connector — status endpoint, no-op when unconfigured."""

from app.cloud.service import get_cloud_status, forward_telemetry


def test_cloud_status_unconfigured():
    status = get_cloud_status()
    assert status["configured"] is False
    assert status["connected"] is False


async def test_forward_telemetry_noop_when_unconfigured():
    """forward_telemetry should silently no-op when cloud_url is empty."""
    await forward_telemetry("node-01", {"temp_f": 75.0})


async def test_cloud_status_api(client):
    r = client.get("/api/cloud/status")
    assert r.status_code == 200
    data = r.json()
    assert data["configured"] is False
    assert data["connected"] is False


async def test_cloud_reconnect_api(client):
    r = client.post("/api/cloud/reconnect")
    assert r.status_code == 200
    assert r.json()["status"] == "not_configured"
