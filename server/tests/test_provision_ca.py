"""GET /api/provision/ca must find the broker CA in every documented run mode.

A node with the portal's "Secure MQTT" toggle fetches the CA from here once
(trust-on-first-use). When the fetch fails the firmware falls back to
plaintext 1883 with only a Serial-console line, so a path that is never
reachable silently turns TLS off for the whole fleet:

* Docker (install.sh): the server container sees the CA only through the
  single-file bind mount at /certs/ca.crt (docker-compose.yml).
* Bare metal: `cd server && uvicorn …` runs with CWD=server/, while
  install.sh/setup.sh write the CA to <repo>/config/mosquitto/certs/ — so the
  fallback path must be anchored at the repo root, not the CWD.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app import provision

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"


def _server_bind_targets() -> dict[str, dict]:
    server = yaml.safe_load(COMPOSE.read_text())["services"]["server"]
    out: dict[str, dict] = {}
    for vol in server.get("volumes", []):
        if isinstance(vol, dict) and vol.get("type") == "bind":
            out[vol["target"]] = vol
    return out


def test_container_ca_path_is_actually_mounted_into_the_server():
    container_path = provision._CA_PATHS[0]
    assert container_path == Path("/certs/ca.crt")
    mounts = _server_bind_targets()
    assert str(container_path) in mounts, (
        "docker-compose.yml never mounts the broker CA into the server "
        "container — /api/provision/ca 404s and Secure MQTT nodes fall back "
        "to plaintext"
    )
    mount = mounts[str(container_path)]
    assert mount["source"] == "./config/mosquitto/certs/ca.crt"
    assert mount.get("read_only") is True


def test_server_never_gets_the_broker_or_ca_private_keys():
    """Only the public CA certificate — never the certs directory (ca.key,
    server.key). The server's appuser is uid 1000, typically the same uid
    as the installing host user, so a chmod 600 would not protect them."""
    for target, mount in _server_bind_targets().items():
        src = mount["source"]
        assert not src.rstrip("/").endswith("config/mosquitto/certs"), (
            f"server mounts the whole certs dir at {target}"
        )
        assert not src.endswith(".key"), f"server mounts a private key: {src}"


def test_bare_metal_ca_path_is_anchored_at_the_repo_root():
    repo_path = provision._CA_PATHS[1]
    assert repo_path.is_absolute(), (
        "CWD-relative CA path — `cd server && uvicorn` would look in "
        "server/config/… where nothing is ever generated"
    )
    assert repo_path == REPO_ROOT / "config" / "mosquitto" / "certs" / "ca.crt"


async def test_provision_ca_serves_repo_root_ca_from_any_cwd(
        client, tmp_path, monkeypatch):
    fake_root_ca = tmp_path / "repo" / "config" / "mosquitto" / "certs" / "ca.crt"
    fake_root_ca.parent.mkdir(parents=True)
    fake_root_ca.write_text(
        "-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----\n")
    monkeypatch.setattr(provision, "_CA_PATHS",
                        (tmp_path / "absent" / "ca.crt", fake_root_ca))
    monkeypatch.chdir(tmp_path)  # a CWD where nothing relative resolves
    resp = client.get("/api/provision/ca")
    assert resp.status_code == 200
    assert "BEGIN CERTIFICATE" in resp.text


async def test_provision_ca_is_public_when_the_api_key_gate_is_on(
        client, tmp_path, monkeypatch):
    """The firmware's TOFU fetch (tls_transport.h) sends no bearer, so with
    SPOREPRINT_API_KEY set the CA must still be served — a 401 here makes
    every Secure-MQTT node fall back to plaintext 1883."""
    from app.config import settings

    ca = tmp_path / "ca.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----\n")
    monkeypatch.setattr(provision, "_CA_PATHS", (ca,))
    monkeypatch.setattr(settings, "api_key", "lan-key")

    resp = client.get("/api/provision/ca")
    assert resp.status_code == 200
    assert "BEGIN CERTIFICATE" in resp.text
    # Only the read is public: other methods and the rest of the API stay gated.
    assert client.post("/api/provision/ca").status_code == 401
    assert client.get("/api/sessions").status_code == 401


async def test_provision_ca_404_points_at_the_supported_installer(
        client, tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "_CA_PATHS", (tmp_path / "nope.crt",))
    resp = client.get("/api/provision/ca")
    assert resp.status_code == 404
    assert "install.sh" in resp.json()["detail"]
