from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: str = "data/db/sporeprint.db"
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    ntfy_url: str = "http://localhost:8080"
    ntfy_topic: str = "sporeprint"
    vision_storage: str = "data/vision"
    claude_api_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_prefix": "SPOREPRINT_", "env_file": ".env"}


settings = Settings()
