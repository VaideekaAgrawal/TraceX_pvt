import pytest

from foundation.config import Settings, get_settings


def test_settings_load_with_defaults():
    settings = Settings()
    assert settings.env == "dev"
    assert settings.database_url.startswith("sqlite:///")


def test_database_url_default_points_to_repo_root_not_cwd():
    # Regression test: the default used to be cwd-relative ("./data/tracex.db"),
    # which resolved to a nonexistent backend/data/ when run from backend/ (the
    # working directory both CI and the documented dev workflow use) — verified
    # by reproducing sqlite3.OperationalError before this was fixed.
    # The default now targets the committed crisp demo DB (tracex_demo.db) so a
    # fresh clone works out of the box; still repo-root-anchored, not cwd-relative.
    settings = Settings()
    assert settings.database_url.endswith("/data/tracex_demo.db")
    assert "backend/data" not in settings.database_url


def test_validate_secrets_fails_loudly_when_missing_in_non_dev():
    settings = Settings(env="prod", jwt_secret="", openrouter_api_key="", pii_hmac_key="")
    with pytest.raises(RuntimeError, match="jwt_secret"):
        settings.validate_secrets()


def test_validate_secrets_passes_in_dev_without_secrets():
    settings = Settings(env="dev")
    settings.validate_secrets()  # must not raise


def test_validate_secrets_requires_llm_key_in_non_dev():
    # ROADMAP Phase 8: Phase 2 deliberately did NOT require this, on the
    # grounds that no code called the LLM gateway yet. Phase 8 is the phase
    # that puts it on the request path, so a non-dev boot without it must now
    # fail at startup rather than degrading every AI surface to "not
    # configured" at the first investigator request.
    settings = Settings(env="prod", jwt_secret="real", openrouter_api_key="", pii_hmac_key="k")
    with pytest.raises(RuntimeError, match="openrouter_api_key"):
        settings.validate_secrets()


def test_validate_secrets_requires_pii_hmac_key_in_non_dev():
    # ROADMAP Phase 8 (committed decision 9): without this key,
    # `Relationship.value_hash` would fall back to an unkeyed SHA256 of a
    # low-entropy identifier — brute-forceable if the DB leaks. Failing closed
    # at boot is the point; a silently-unkeyed hash is the bug.
    settings = Settings(env="prod", jwt_secret="real", openrouter_api_key="k", pii_hmac_key="")
    with pytest.raises(RuntimeError, match="pii_hmac_key"):
        settings.validate_secrets()


def test_validate_secrets_passes_in_non_dev_with_all_secrets():
    settings = Settings(
        env="prod", jwt_secret="real", openrouter_api_key="k", pii_hmac_key="h"
    )
    settings.validate_secrets()  # must not raise


def test_get_settings_is_cached():
    assert get_settings() is get_settings()
