from typing import Literal

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Model used by every Claude feature unless SPOREPRINT_CLAUDE_MODEL overrides it.
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"


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
    # Model id for every Claude call (vision frame analysis, contamination
    # identify, transcript + experiment analysis, Builder's Assistant). One
    # knob so a model retirement is an env change, not a code change. Blank
    # (e.g. compose's `${SPOREPRINT_CLAUDE_MODEL:-}`) means the default.
    claude_model: str = DEFAULT_CLAUDE_MODEL
    weather_provider: str = "openmeteo"  # "openmeteo" | "openweathermap" | "nws"
    weather_api_key: str = ""  # only needed for openweathermap
    weather_lat: str = ""
    weather_lon: str = ""
    weather_poll_minutes: int = 10
    # Minutes between automatic Claude analyses of a session's camera frames
    # (vision/service._auto_analysis_interval_seconds). The local CNN is still
    # a stub, so this is the worst-case automatic contamination-detection
    # latency; lower it for faster detection at more BYOK API spend. The first
    # frame after a phase change is always analysed at once. Values <= 0 fall
    # back to the 6 h default.
    vision_auto_interval_min: int = 360
    cloud_url: str = ""
    cloud_token: str = ""
    cloud_device_id: str = ""
    # Strict mode for cloud integrations_request frames
    # (cloud/integrations_proxy._require_signed_setting): true rejects every
    # unsigned frame. False keeps the migration posture — unsigned frames are
    # accepted until this Pi verifies its first signed one after pairing.
    cloud_require_signed_integrations: bool = False
    # Where the operator's browser reaches the Pi dashboard (nginx UI port),
    # e.g. for links printed on QR labels. The default is the mDNS name plus
    # the compose UI port. Its host is also an allowed Host header (below).
    public_ui_url: str = "http://sporeprint.local:3001"
    # DNS-rebinding guard (app/host_allow.py): requests are served only for
    # Host names no outside attacker can point at the Pi — IP literals in
    # private ranges, localhost, *.local/*.lan/*.home.arpa/*.internal, dotless
    # names and public_ui_url's host. Comma list of extra names ("pi.example.
    # net"), "*.suffix" wildcards, IPs or CIDRs you reach the Pi by; "*"
    # disables the check.
    allowed_hosts: str = ""
    # If set, all /api/* requests and Socket.IO connects must present
    # Authorization: Bearer <api_key>. Empty means no auth. install.sh
    # leaves it empty and writes SPOREPRINT_ALLOW_UNAUTHENTICATED=true
    # (LAN-trust, the bundled dashboard sends no bearer); set it to gate the
    # mobile app and other external clients.
    api_key: str = ""
    # Explicit opt-in to run with api_key unset. Default false — an empty
    # api_key will refuse to boot unless this flag is true. Prevents silently
    # shipping a production Pi with no auth because the operator skipped
    # ./install.sh or forgot to set SPOREPRINT_API_KEY.
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

    # extra="ignore": bare metal reads server/.env, and a copy of the
    # repo-root .env carries TZ, FORWARDED_ALLOW_IPS and compose-only keys.
    # Refusing unknown keys ("Extra inputs are not permitted") kept the server
    # from booting at all. env_ignore_empty is deliberately NOT set: a blank
    # str keeps its meaning (an empty ntfy_url disables notifications); blank
    # non-str values are handled by _blank_non_str_is_default below.
    model_config = SettingsConfigDict(
        env_prefix="SPOREPRINT_", env_file=".env", extra="ignore",
    )

    @field_validator("*", mode="before")
    @classmethod
    def _blank_non_str_is_default(cls, value, info: ValidationInfo):
        """`SPOREPRINT_PORT=` means the default, not a boot-time crash loop.

        A kept-but-emptied key (compose `${VAR:-}`, an edited .env) failed
        int/bool/Literal validation. Every non-str default is the safe one
        (allow_unauthenticated=False, mqtt_require_signing="auto"). A
        malformed non-blank value still fails loudly.
        """
        if isinstance(value, str) and not value.strip():
            field = cls.model_fields[info.field_name]
            if field.annotation is not str:
                return field.get_default(call_default_factory=True)
        return value

    @field_validator("claude_model", mode="before")
    @classmethod
    def _blank_claude_model_is_default(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return DEFAULT_CLAUDE_MODEL
        return value.strip() if isinstance(value, str) else value


settings = Settings()
