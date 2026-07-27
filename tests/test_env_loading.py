"""Issue 59 — entry points load `.env` before config resolution.

Covers src.gen_run.load_env_file, src.daily_upload.load_env_file, and
src.bootstrap.load_env_file: a fake key/value pair loads into os.environ, a
value already set in the real environment is never overridden, and a missing
`.env` file does not raise. All tests use monkeypatch + tmp_path — never the
developer's real `.env`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import bootstrap, daily_upload, gen_run


MODULES = [gen_run, daily_upload, bootstrap]


def _write_env(tmp_path: Path, contents: str) -> Path:
    env_path = tmp_path / ".env"
    env_path.write_text(contents, encoding="utf-8")
    return env_path


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__)
def test_load_env_file_populates_os_environ(module, tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIA_AGENT_TEST_VAR", raising=False)
    _write_env(tmp_path, "MEDIA_AGENT_TEST_VAR=from-dotenv\n")

    module.load_env_file(tmp_path)

    assert __import__("os").environ["MEDIA_AGENT_TEST_VAR"] == "from-dotenv"


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__)
def test_load_env_file_does_not_override_real_environment(module, tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_AGENT_TEST_VAR", "from-shell")
    _write_env(tmp_path, "MEDIA_AGENT_TEST_VAR=from-dotenv\n")

    module.load_env_file(tmp_path)

    assert __import__("os").environ["MEDIA_AGENT_TEST_VAR"] == "from-shell"


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__)
def test_load_env_file_missing_file_does_not_raise(module, tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIA_AGENT_TEST_VAR", raising=False)
    # No .env written at all in this empty tmp_path.

    module.load_env_file(tmp_path)  # must not raise

    assert "MEDIA_AGENT_TEST_VAR" not in __import__("os").environ


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__)
def test_load_env_file_never_logs_or_returns_secret(module, tmp_path, monkeypatch, capsys):
    """The loader itself must not print anything containing the loaded value."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    secret = "sk-or-v1-" + "a" * 64
    _write_env(tmp_path, f"OPENROUTER_API_KEY={secret}\n")

    module.load_env_file(tmp_path)

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_gen_run_main_loads_env_before_config_resolution(tmp_path, monkeypatch):
    """The entry point's main() must call load_env_file() before load_config()
    — order matters because config resolution may read env-derived values."""
    import argparse

    monkeypatch.delenv("MEDIA_AGENT_TEST_VAR", raising=False)

    call_order = []

    def fake_load_env_file(root=None):
        call_order.append("load_env_file")

    def fake_load_config(config_path):
        call_order.append("load_config")
        raise SystemExit(0)  # short-circuit before any real pipeline work

    monkeypatch.setattr(gen_run, "load_env_file", fake_load_env_file)
    monkeypatch.setattr(gen_run, "load_config", fake_load_config)
    monkeypatch.setattr("sys.argv", ["gen_run"])

    with pytest.raises(SystemExit):
        gen_run.main()

    assert call_order == ["load_env_file", "load_config"]


def test_daily_upload_main_loads_env_before_config_resolution(tmp_path, monkeypatch):
    call_order = []

    def fake_load_env_file(root=None):
        call_order.append("load_env_file")

    def fake_load_config(config_path):
        call_order.append("load_config")
        raise SystemExit(0)

    monkeypatch.setattr(daily_upload, "load_env_file", fake_load_env_file)
    monkeypatch.setattr(daily_upload, "load_config", fake_load_config)
    monkeypatch.setattr("sys.argv", ["daily_upload"])

    with pytest.raises(SystemExit):
        daily_upload.main()

    assert call_order == ["load_env_file", "load_config"]
