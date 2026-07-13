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
    settings = Settings()
    assert settings.database_url.endswith("/data/tracex.db")
    assert "backend/data" not in settings.database_url


def test_validate_secrets_fails_loudly_when_missing_in_non_dev():
    settings = Settings(env="prod", jwt_secret="", openrouter_api_key="", pii_hmac_secret="")
    with pytest.raises(RuntimeError, match="jwt_secret"):
        settings.validate_secrets()


def test_validate_secrets_fails_loudly_when_pii_hmac_secret_missing_in_non_dev():
    # Regression test (ROADMAP Phase 8): pii_hmac_secret joins jwt_secret as
    # a required-outside-dev secret once relationship_discovery's HMAC fix
    # lands -- must not be silently skippable like openrouter_api_key is.
    settings = Settings(
        env="prod", jwt_secret="real-secret", openrouter_api_key="", pii_hmac_secret=""
    )
    with pytest.raises(RuntimeError, match="pii_hmac_secret"):
        settings.validate_secrets()


def test_validate_secrets_passes_in_dev_without_secrets():
    settings = Settings(env="dev")
    settings.validate_secrets()  # must not raise


def test_validate_secrets_ignores_missing_openrouter_key_in_non_dev():
    # Regression test (code review, Phase 2): nothing calls the LLM gateway
    # at app-startup time, so a non-dev boot must not fail over a secret
    # startup itself doesn't use -- `foundation.llm_gateway` checks it at
    # the point a provider is actually constructed instead.
    settings = Settings(
        env="prod", jwt_secret="real-secret", openrouter_api_key="", pii_hmac_secret="real-secret"
    )
    settings.validate_secrets()  # must not raise


def test_get_settings_is_cached():
    assert get_settings() is get_settings()
