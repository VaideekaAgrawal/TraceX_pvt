import pytest

from foundation.config import Settings, get_settings


def test_settings_load_with_defaults():
    settings = Settings()
    assert settings.env == "dev"
    assert settings.database_url.startswith("sqlite:///")


def test_validate_secrets_fails_loudly_when_missing_in_non_dev():
    settings = Settings(env="prod", jwt_secret="", openrouter_api_key="")
    with pytest.raises(RuntimeError, match="jwt_secret"):
        settings.validate_secrets()


def test_validate_secrets_passes_in_dev_without_secrets():
    settings = Settings(env="dev")
    settings.validate_secrets()  # must not raise


def test_get_settings_is_cached():
    assert get_settings() is get_settings()
