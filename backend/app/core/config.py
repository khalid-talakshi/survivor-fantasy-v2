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
    supabase_jwks_url: str = "https://YOUR_PROJECT.supabase.co/auth/v1/.well-known/jwks.json"
    supabase_jwt_issuer: str = "https://YOUR_PROJECT.supabase.co/auth/v1"
    supabase_jwt_audience: str = "authenticated"
    supabase_jwks_cache_seconds: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
