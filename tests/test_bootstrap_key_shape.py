"""Issue 59 — bootstrap --check validates OPENROUTER_API_KEY shape.

`check_openrouter_key()` must fail (not warn) on a missing key, fail on a
malformed key (distinct message from missing), and pass on a well-formed
`sk-or-v1-<64 hex>` key — without ever echoing the key value.
"""

from __future__ import annotations

import pytest

from src import bootstrap


VALID_KEY = "sk-or-v1-" + "0123456789abcdef" * 4  # 64 hex chars
PLACEHOLDER_KEY = "sk-or-v1-bad"  # 13 chars, mirrors the real repo's placeholder


def test_absent_key_fails(monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    result = bootstrap.check_openrouter_key()

    assert result is False
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "absent" in out.lower() or "not set" in out.lower()


def test_malformed_key_fails_with_distinct_message(monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", PLACEHOLDER_KEY)

    result = bootstrap.check_openrouter_key()

    assert result is False
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "malformed" in out.lower()
    assert "absent" not in out.lower() and "not set" not in out.lower()


def test_well_formed_key_passes(monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", VALID_KEY)

    result = bootstrap.check_openrouter_key()

    assert result is True
    out = capsys.readouterr().out
    assert "OK" in out


@pytest.mark.parametrize("key", [PLACEHOLDER_KEY, VALID_KEY])
def test_key_value_never_echoed(monkeypatch, capsys, key):
    monkeypatch.setenv("OPENROUTER_API_KEY", key)

    bootstrap.check_openrouter_key()

    out = capsys.readouterr().out
    assert key not in out


def test_absent_and_malformed_messages_differ(monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    bootstrap.check_openrouter_key()
    absent_out = capsys.readouterr().out

    monkeypatch.setenv("OPENROUTER_API_KEY", PLACEHOLDER_KEY)
    bootstrap.check_openrouter_key()
    malformed_out = capsys.readouterr().out

    assert absent_out != malformed_out


def test_short_placeholder_prefix_reported_safely(monkeypatch, capsys):
    """A key shorter than the prefix length must not crash the length/prefix
    reporting path (regression guard for the current 13-char placeholder)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "short")

    result = bootstrap.check_openrouter_key()

    assert result is False
    out = capsys.readouterr().out
    assert "short" not in out  # the value itself must not be echoed
