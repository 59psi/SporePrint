from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: str = "data/db/sporeprint.db"
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    ntfy_url: str = "http://localhost:8080"
    ntfy_topic: str = "sporeprint"
    vision_storage: str = "data/vision"
    claude_api_key: str = ""
    weather_provider: str = "openmeteo"  # "openmeteo" | "openweathermap" | "nws"
    weather_api_key: str = ""  # only needed for openweathermap
    weather_lat: str = ""
    weather_lon: str = ""
    weather_poll_minutes: int = 10
    cloud_url: str = ""
    cloud_token: str = ""
    cloud_device_id: str = ""
    # If set, all /api/* requests and Socket.IO connects must present
    # Authorization: Bearer <api_key>. Empty means no auth.
    # setup.sh populates this on first run so the default is authed.
    api_key: str = ""
    # Explicit opt-in to run with api_key unset. Default false — an empty
    # api_key will refuse to boot unless this flag is true. Prevents silently
    # shipping a production Pi with no auth because the operator never ran
    # setup.sh or forgot to set SPOREPRINT_API_KEY.
    allow_unauthenticated: bool = False
    # HMAC-SHA256 key used to sign every cmd/* MQTT frame the Pi publishes
    # to an ESP32 node. v3.4.9 C-1. Must match the `hmac_key` stored in NVS
    # on each node. Use scripts/provision-node.sh to generate and deploy.
    mqtt_hmac_key: str = ""
    # Command-signing enforcement — how the Pi behaves when it publishes a
    # cmd/* frame but mqtt_hmac_key is UNSET (when the key IS set, frames are
    # always signed):
    #   "auto"   — enforce iff this Pi is cloud-configured (cloud_url set): a
    #              cloud-paired / managed deployment refuses to ship unsigned
    #              commands; a pure-LAN self-host stays permissive (LAN-trust).
    #              Keyed off the STABLE config, not the live connection, so a
    #              cloud outage / DoS can't silently downgrade signing.
    #   "always" — always enforce.
    #   "never"  — never enforce (ship unsigned on a trusted LAN).
    # Enforcing REFUSES the unsigned publish and logs a CRITICAL with
    # remediation, instead of the old silent fail-open; state is surfaced at
    # GET /api/health/detail/mqtt and logged once at MQTT startup. A
    # provisioned node rejects unsigned frames regardless, so keyed fleets are
    # unaffected by this policy either way.
    mqtt_require_signing: Literal["auto", "always", "never"] = "auto"
    host: str = "0.0.0.0"
    port: int = 8000
    # OTA self-update — base64-encoded raw 32-byte Ed25519 public key.
    # Empty = OTA fails closed with "OTA public key not configured".
    # Generate via scripts/generate-ota-keypair.py; private key never
    # leaves the release-signing host.
    ota_pubkey_b64: str = ""
    # First-run wizard flag. "0" = auto-launch on UI boot; "1" = done.
    setup_complete: str = "0"
    # v4.1 third-party integrations — Fernet key used to encrypt secret
    # fields (API keys, tokens) inside `integration_settings.config`.
    # Generated on first use if the file does not exist; mode 0600.
    # Loss of this file means re-entering credentials, which is
    # acceptable — there is intentionally no remote-recovery path.
    integration_key_path: str = "data/db/.integration-key"

    model_config = {"env_prefix": "SPOREPRINT_", "env_file": ".env"}


settings = Settings()
