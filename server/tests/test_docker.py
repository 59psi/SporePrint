"""Validate docker-compose.yml — catches image typos, missing services, wrong env vars."""

from pathlib import Path

import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _load_compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text())


def test_compose_has_all_services():
    services = _load_compose()["services"]
    for name in ("server", "mqtt", "ntfy", "ui"):
        assert name in services, f"Missing service: {name}"


def test_ntfy_image_is_correct():
    services = _load_compose()["services"]
    assert services["ntfy"]["image"] == "binwiederhier/ntfy"


def test_mosquitto_image_is_correct():
    services = _load_compose()["services"]
    assert services["mqtt"]["image"] == "eclipse-mosquitto:2"


def test_server_env_vars_use_correct_prefix():
    services = _load_compose()["services"]
    env_list = services["server"]["environment"]
    for env in env_list:
        key = env.split("=")[0]
        assert key.startswith("SPOREPRINT_"), f"Env var {key} doesn't use SPOREPRINT_ prefix"


def test_ui_port_mapping():
    services = _load_compose()["services"]
    ports = services["ui"]["ports"]
    assert any("3001:80" in str(p) for p in ports), f"UI should map to port 3001, got {ports}"
