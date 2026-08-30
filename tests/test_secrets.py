from app.infrastructure.secrets import get_secret


def test_local_secret_value_never_calls_key_vault():
    get_secret.cache_clear()
    assert get_secret("unused-secret", "local-development-value") == "local-development-value"
