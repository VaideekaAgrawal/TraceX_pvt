"""
Application configuration — the single source of truth for settings/secrets.

All values are read from the environment (or a local .env for dev only,
never committed). Nothing security-sensitive gets a hardcoded default —
that was the old system's landmine (JWT_SECRET = "CHANGE_ME_IN_PRODUCTION",
see CLAUDE.md). If a secret is missing, startup fails loudly instead of
falling back to an insecure default.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/foundation/config.py -> foundation/ -> backend/ -> repo root.
# Computed from this file's location (not cwd) so the default DB path is
# correct no matter where the process is launched from — CI and the README
# both run from backend/, where a cwd-relative "./data" would resolve to a
# nonexistent backend/data/ instead of the real repo-root data/ that Phase 0
# lifted the source CSVs into. Verified: a cwd-relative default raised
# sqlite3.OperationalError when a DB connection was opened from backend/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SQLITE_PATH = _REPO_ROOT / "data" / "tracex.db"
# Same reasoning applies to the ML/RL model artifact directory (ROADMAP
# Phase 3): `train_and_persist()` serializes trained model objects here via
# joblib, and `model_runs.artifact_path` points into it. Gitignored — these
# are generated, not source.
_DEFAULT_MODEL_ARTIFACT_DIR = _REPO_ROOT / "data" / "model_artifacts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── App ──
    env: str = Field(default="dev")  # dev | staging | prod
    log_level: str = Field(default="INFO")

    # ── Database ──
    # SQLite for pilot/dev, Postgres DSN for production — see docs/DATA_SCHEMA.md §0.
    database_url: str = Field(default=f"sqlite:///{_DEFAULT_SQLITE_PATH}")

    # ── ML/RL model artifacts (ROADMAP Phase 3) ──
    # Where trained ensemble artifacts (joblib) are written; model_runs.
    # artifact_path stores a path under this directory. Trained once by
    # `scripts/train_detection_model.py`, never retrained on app boot.
    model_artifact_dir: Path = Field(default=_DEFAULT_MODEL_ARTIFACT_DIR)

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
        can construct Settings() without secrets configured.

        Only checks `jwt_secret` — every phase up to and including Phase 2
        needs it. `openrouter_api_key` is deliberately NOT checked here: no
        code calls the LLM gateway yet (it doesn't exist until Phase 8), so
        requiring it today would make any non-dev boot of the current
        auth-only API fail for a secret nothing uses. Phase 8 should add its
        own check at the point the LLM gateway is actually constructed, not
        here (code review finding, Phase 2: this method was previously never
        invoked anywhere, so this over-broad requirement was latent until
        Phase 2 wired it into real app startup)."""
        if self.env != "dev":
            missing = []
            if not self.jwt_secret:
                missing.append("jwt_secret")
            if missing:
                raise RuntimeError(
                    f"Missing required secrets for env={self.env}: {', '.join(missing)}"
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
