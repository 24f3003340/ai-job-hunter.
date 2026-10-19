from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOBHUNTER_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./jobhunter.db"
    session_ttl_hours: int = 24 * 7
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
