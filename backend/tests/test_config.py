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
    settings = Settings(env="prod", jwt_secret="", openrouter_api_key="")
    with pytest.raises(RuntimeError, match="jwt_secret"):
        settings.validate_secrets()


def test_validate_secrets_passes_in_dev_without_secrets():
    settings = Settings(env="dev")
    settings.validate_secrets()  # must not raise


def test_get_settings_is_cached():
    assert get_settings() is get_settings()
