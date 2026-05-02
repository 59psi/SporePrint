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
    # on each node. Empty = unsigned (migration period; nodes log WARNING
    # per command). Use scripts/provision-node.sh to generate and deploy.
    mqtt_hmac_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    # OTA self-update — base64-encoded raw 32-byte Ed25519 public key.
    # Empty = OTA fails closed with "OTA public key not configured".
    # Generate via scripts/generate-ota-keypair.py; private key never
    # leaves the release-signing host.
    ota_pubkey_b64: str = ""
    # First-run wizard flag. "0" = auto-launch on UI boot; "1" = done.
    setup_complete: str = "0"

    model_config = {"env_prefix": "SPOREPRINT_", "env_file": ".env"}


settings = Settings()
