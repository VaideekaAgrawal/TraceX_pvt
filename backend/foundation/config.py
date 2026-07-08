"""
Application configuration — the single source of truth for settings/secrets.

All values are read from the environment (or a local .env for dev only,
never committed). Nothing security-sensitive gets a hardcoded default —
that was the old system's landmine (JWT_SECRET = "CHANGE_ME_IN_PRODUCTION",
see CLAUDE.md). If a secret is missing, startup fails loudly instead of
falling back to an insecure default.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── App ──
    env: str = Field(default="dev")  # dev | staging | prod
    log_level: str = Field(default="INFO")

    # ── Database ──
    # SQLite for pilot/dev, Postgres DSN for production — see docs/DATA_SCHEMA.md §0.
    database_url: str = Field(default="sqlite:///./data/tracex.db")

    # ── Auth (no default in staging/prod — see Settings.validate_secrets) ──
    jwt_secret: str = Field(default="")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiry_minutes: int = Field(default=60 * 8)

    # ── LLM gateway (ROADMAP Phase 8) ──
    llm_provider: str = Field(default="openrouter")
    openrouter_api_key: str = Field(default="")
    llm_model: str = Field(default="anthropic/claude-opus-4.8")

    # ── Graph engine ──
    graph_backend: str = Field(default="networkx")  # networkx | neo4j (future)
    neo4j_uri: str = Field(default="")
    neo4j_user: str = Field(default="")
    neo4j_password: str = Field(default="")

    def validate_secrets(self) -> None:
        """Fail startup loudly instead of silently running insecure.
        Called explicitly by the app factory, not at import time, so tests
        can construct Settings() without secrets configured."""
        if self.env != "dev":
            missing = []
            if not self.jwt_secret:
                missing.append("jwt_secret")
            if self.llm_provider == "openrouter" and not self.openrouter_api_key:
                missing.append("openrouter_api_key")
            if missing:
                raise RuntimeError(
                    f"Missing required secrets for env={self.env}: {', '.join(missing)}"
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
