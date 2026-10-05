import os

from tastydb.config import Config, load_dotenv


def test_load_dotenv_parses_and_feeds_config(tmp_path, monkeypatch):
    monkeypatch.delenv("TT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TT_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("TASTYDB_MATCH_METHOD", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# credentials\n"
        "TT_CLIENT_SECRET=abc123\n"
        'export TT_REFRESH_TOKEN="tok+with=equals"\n'
        "TASTYDB_MATCH_METHOD='LIFO'\n"
        "\n"
        "not a valid line\n"
    )
    applied = load_dotenv(env_file)
    try:
        assert applied == {
            "TT_CLIENT_SECRET": "abc123",
            "TT_REFRESH_TOKEN": "tok+with=equals",
            "TASTYDB_MATCH_METHOD": "LIFO",
        }
        config = Config()
        assert config.has_credentials
        assert config.refresh_token == "tok+with=equals"
        assert config.match_method == "lifo"
    finally:
        for key in applied:
            os.environ.pop(key, None)


def test_load_dotenv_never_overrides_real_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TT_CLIENT_SECRET", "from-real-env")
    env_file = tmp_path / ".env"
    env_file.write_text("TT_CLIENT_SECRET=from-dotenv\n")
    applied = load_dotenv(env_file)
    assert applied == {}
    assert os.environ["TT_CLIENT_SECRET"] == "from-real-env"


def test_load_dotenv_missing_file_is_noop(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == {}


def test_each_environment_gets_its_own_default_database(monkeypatch):
    monkeypatch.delenv("TASTYDB_DB_URL", raising=False)
    monkeypatch.delenv("TT_ENV", raising=False)
    assert Config().resolved_db_url == "sqlite:///tastydb.sqlite3"
    assert Config(env="sandbox").resolved_db_url == "sqlite:///tastydb-sandbox.sqlite3"

    # flipping env after construction (the --sandbox flag) still resolves right
    config = Config()
    config.env = "sandbox"
    assert config.resolved_db_url == "sqlite:///tastydb-sandbox.sqlite3"


def test_explicit_db_url_overrides_per_environment_default(monkeypatch):
    monkeypatch.setenv("TASTYDB_DB_URL", "sqlite:///custom.sqlite3")
    config = Config(env="sandbox")
    assert config.resolved_db_url == "sqlite:///custom.sqlite3"


def _fake_keyring(monkeypatch, store):
    import keyring

    calls = []

    def get_password(service, entry):
        calls.append((service, entry))
        return store.get((service, entry))

    monkeypatch.setattr(keyring, "get_password", get_password)
    monkeypatch.setenv("TASTYDB_KEYRING", "on")
    return calls


def test_credentials_fall_back_to_cherrypick_keyring_entry(monkeypatch):
    monkeypatch.delenv("TT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TT_REFRESH_TOKEN", raising=False)
    calls = _fake_keyring(monkeypatch, {
        ("cherrypick-broker", "production:client_secret"): "kr-secret",
        ("cherrypick-broker", "production:refresh_token"): "kr-token",
    })
    config = Config()
    assert calls == []  # lazy: constructing a Config never touches the keyring
    assert config.has_credentials
    assert (config.client_secret, config.refresh_token) == ("kr-secret", "kr-token")


def test_env_beats_keyring_and_sandbox_skips_it(monkeypatch):
    monkeypatch.setenv("TT_CLIENT_SECRET", "env-secret")
    monkeypatch.delenv("TT_REFRESH_TOKEN", raising=False)
    calls = _fake_keyring(monkeypatch, {
        ("cherrypick-broker", "production:client_secret"): "kr-secret",
        ("cherrypick-broker", "production:refresh_token"): "kr-token",
    })
    config = Config()
    assert config.has_credentials
    assert config.client_secret == "env-secret" and config.refresh_token == "kr-token"

    sandbox = Config()
    sandbox.client_secret = sandbox.refresh_token = None
    sandbox.env = "sandbox"
    n = len(calls)
    assert not sandbox.has_credentials  # prod tokens are never offered to the cert env
    assert len(calls) == n


def test_keyring_failure_degrades_to_no_credentials(monkeypatch):
    import keyring

    monkeypatch.delenv("TT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TT_REFRESH_TOKEN", raising=False)
    monkeypatch.setenv("TASTYDB_KEYRING", "on")

    def boom(*a):
        raise keyring.errors.NoKeyringError("none")

    monkeypatch.setattr(keyring, "get_password", boom)
    assert not Config().has_credentials
