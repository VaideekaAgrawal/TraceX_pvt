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

    # ── LLM gateway (ROADMAP Phase 8, committed decision 6) ──
    # The gateway speaks the OpenAI chat-completions schema via the `openai`
    # SDK, pointed at `llm_base_url`. That schema IS the portable provider
    # interface (OpenRouter, vLLM, TGI and Ollama all serve it), so a
    # bank-mandated on-prem swap is a base_url change, not a rewrite — which
    # is why there is deliberately no further provider-abstraction layer.
    llm_provider: str = Field(default="openrouter")
    llm_base_url: str = Field(default="https://openrouter.ai/api/v1")
    openrouter_api_key: str = Field(default="")
    # Chosen on measured behavior against the REAL account-explanation prompt,
    # not on sticker price (docs/METRICS.md §11). Two things that per-token
    # pricing hides, both verified live against OpenRouter:
    #
    #   1. Reasoning models bill their hidden reasoning as output tokens, and
    #      `max_tokens` is shared between reasoning and visible content. On this
    #      prompt `openai/gpt-5` spent 1280 tokens reasoning to emit 220 visible
    #      ones — making it BOTH slower (21.6s vs 6.1s) and more expensive
    #      ($0.0154 vs $0.0041/call) than this non-reasoning model, despite a
    #      "cheaper" headline rate. Do not pick a reasoning model here on the
    #      strength of its $/token alone; measure $/explanation.
    #   2. Verified this model reports both `tools` and `structured_outputs` in
    #      `supported_parameters` via `GET {llm_base_url}/models`. Phase 8's
    #      substrate (tool catalog + structured grounding contract) is unusable
    #      without function-calling — never swap in a model lacking it.
    llm_model: str = Field(default="anthropic/claude-sonnet-4.5")

    # ── PII (ROADMAP Phase 8, committed decision 9) ──
    # Keys `Relationship.value_hash`'s HMAC-SHA256. A bare SHA256 of a
    # low-entropy identifier (a PAN is 10 chars from a known alphabet) is
    # brute-forceable if the DB ever leaks; keying it makes the digest
    # useless without this secret. Relationship rows are derived, so rotating
    # this key is a regenerate via `scripts/discover_relationships.py`, not a
    # migration.
    pii_hmac_key: str = Field(default="")

    # ── Graph engine ──
    graph_backend: str = Field(default="networkx")  # networkx | neo4j (future)
    neo4j_uri: str = Field(default="")
    neo4j_user: str = Field(default="")
    neo4j_password: str = Field(default="")

    def validate_secrets(self) -> None:
        """Fail startup loudly instead of silently running insecure.
        Called explicitly by the app factory, not at import time, so tests
        can construct Settings() without secrets configured.

        Phase 2 checked only `jwt_secret`, and deliberately deferred the LLM
        key on the grounds that no code called the gateway yet — requiring a
        secret nothing used would have broken non-dev boots of an auth-only
        API for no benefit. Phase 8 is the phase that makes both secrets
        load-bearing on the request path, so both are now required outside
        `dev`:

        - `openrouter_api_key` — without it every AI surface degrades to
          "not configured" at the first investigator request rather than at
          boot, which is exactly the kind of failure a pilot deployment
          should not discover in front of a user.
        - `pii_hmac_key` — without it `Relationship.value_hash` would fall
          back to an unkeyed digest of a low-entropy identifier. Failing
          closed at boot is the point: a silently-unkeyed hash is the bug.

        Both keep an empty default so `dev` and the test suite construct
        `Settings()` freely."""
        if self.env != "dev":
            missing = []
            if not self.jwt_secret:
                missing.append("jwt_secret")
            if not self.openrouter_api_key:
                missing.append("openrouter_api_key")
            if not self.pii_hmac_key:
                missing.append("pii_hmac_key")
            if missing:
                raise RuntimeError(
                    f"Missing required secrets for env={self.env}: {', '.join(missing)}"
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
