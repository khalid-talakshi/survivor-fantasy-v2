from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Survivor Fantasy"
    environment: str = "development"
    database_url: str = Field(
        default=(
            "postgresql+psycopg://survivor_fantasy_runtime:runtime@localhost:5432/"
            "survivor_fantasy"
        )
    )
    frontend_dist: str = "frontend/dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
