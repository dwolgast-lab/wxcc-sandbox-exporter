import pytest
from wxcc_export import config


def write_env(tmp_path, text, name=".env"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_load_config_reads_key_values(tmp_path, monkeypatch):
    write_env(tmp_path, "WXCC_CLIENT_ID=abc\nWXCC_CLIENT_SECRET=shh\n")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    cfg = config.load_config()
    assert cfg["client_id"] == "abc"
    assert cfg["client_secret"] == "shh"


def test_load_config_ignores_comments_and_blank_lines(tmp_path, monkeypatch):
    write_env(tmp_path, "# a comment\n\nWXCC_CLIENT_ID=abc\n   \n")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert config.load_config()["client_id"] == "abc"


def test_load_config_strips_surrounding_quotes(tmp_path, monkeypatch):
    write_env(tmp_path, 'WXCC_CLIENT_ID="abc"\nWXCC_SCOPES=\'cjp:config_read\'\n')
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    cfg = config.load_config()
    assert cfg["client_id"] == "abc"
    assert cfg["scopes"] == "cjp:config_read"


def test_api_base_defaults_to_us_region(tmp_path, monkeypatch):
    write_env(tmp_path, "WXCC_CLIENT_ID=abc\n")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert config.load_config()["api_base"] == "https://api.wxcc-us1.cisco.com"


def test_api_base_trailing_slash_is_stripped(tmp_path, monkeypatch):
    write_env(tmp_path, "WXCC_API_BASE=https://api.wxcc-eu1.cisco.com/\n")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert config.load_config()["api_base"] == "https://api.wxcc-eu1.cisco.com"


def test_profile_selects_a_different_env_file(tmp_path, monkeypatch):
    write_env(tmp_path, "WXCC_CLIENT_ID=default\n")
    write_env(tmp_path, "WXCC_CLIENT_ID=target\n", name=".env.target")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert config.load_config()["client_id"] == "default"
    assert config.load_config("target")["client_id"] == "target"


def test_profile_gets_its_own_token_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert config.token_store(None) != config.token_store("target")


def test_missing_env_file_raises_config_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    with pytest.raises(config.ConfigError) as exc:
        config.load_config("nope")
    assert ".env.nope" in str(exc.value)


def test_real_environment_overrides_the_file(tmp_path, monkeypatch):
    write_env(tmp_path, "WXCC_CLIENT_ID=from_file\n")
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    monkeypatch.setenv("WXCC_CLIENT_ID", "from_env")
    assert config.load_config()["client_id"] == "from_env"


def test_base_dir_is_the_repo_root_when_run_from_source():
    # src/wxcc_export/config.py -> parents[2] is the checkout root.
    assert (config._base_dir() / "pyproject.toml").exists()


def test_base_dir_is_the_executables_folder_when_frozen(tmp_path, monkeypatch):
    # A one-file build unpacks to a temp dir that is deleted on exit; resolving
    # .env and .wxcc/ from __file__ there would lose every stored token.
    exe = tmp_path / "wxcc-export.exe"
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "executable", str(exe))
    assert config._base_dir() == tmp_path.resolve()
