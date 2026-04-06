from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: str = "data/db/sporeprint.db"
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
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
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_prefix": "SPOREPRINT_", "env_file": ".env"}


settings = Settings()
