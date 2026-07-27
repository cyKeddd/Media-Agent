# Issue 59 — Entry points load `.env`; `bootstrap --check` validates the key shape

**Status:** ready-for-agent
**Type:** AFK
**Priority:** 1 (Urgent — the pipeline has produced nothing since 2026-06-02; this is root cause #1)

## Parent

`docs/prds/resurrection-and-image-first-polish.md` — WS1.

## What to build

Make the scheduler-driven entry points see the secrets in `.env`, and make a bad key fail loudly
at check time instead of silently at billing time.

Today `src/gen_run.py` and `src/daily_upload.py` never call `load_dotenv` — only ad-hoc
`scripts/*.py` do. Under Windows Task Scheduler the environment has no `OPENROUTER_API_KEY`, so
`src/gen_run.py:305` raises `RuntimeError("OPENROUTER_API_KEY required for ai_video shots")` and
every run yields `generate_clips=0`. `python-dotenv>=1.0.1` is already in `requirements.txt`.

Compounding it: the value currently in `.env` is **13 characters** — a placeholder. A real
OpenRouter key is `sk-or-v1-` followed by 64 hex characters (~73 total). Loading `.env` alone
would still fail, so the check must catch the shape, not just the presence.

Scope:

- Both `src/gen_run.py` and `src/daily_upload.py` call `load_dotenv(ROOT / ".env")` **before**
  config resolution, matching the pattern already used in `scripts/render_from_script.py:49`.
  Loading must not override a variable already set in the real environment.
- A missing `.env` file is not an error — the env may legitimately be populated by the shell.
- `bootstrap --check` gains an `OPENROUTER_API_KEY` shape check against
  `^sk-or-v1-[0-9a-f]{64}$`, reporting **fail** (not warn) on mismatch, and distinguishing
  "absent" from "malformed" in its message.
- The key value must never be echoed. Log and error text may show a length and a prefix
  (`sk-or-v1-…`, 13 chars) but never the secret.

## Invariants

- **INV-6** — Both entry points load `.env` before config resolution. `bootstrap --check` fails
  when `OPENROUTER_API_KEY` does not match `^sk-or-v1-[0-9a-f]{64}$`. The key never appears in a
  log, alert, or committed file.
- **INV-13** — `.env` stays gitignored; no secret is committed.

## Acceptance criteria

- [ ] `src/gen_run.py` and `src/daily_upload.py` both load `.env` before resolving config.
- [ ] A variable already present in `os.environ` is **not** overridden by the `.env` value.
- [ ] A missing `.env` file does not raise.
- [ ] `bootstrap --check` fails on a malformed key (e.g. the current 13-char placeholder), fails on
      an absent key, and passes on a well-formed one, with different messages for absent vs
      malformed.
- [ ] No test, log line, or error message contains a full key value.
- [ ] Tests use `monkeypatch` + `tmp_path` — no reliance on the developer's real `.env`.

## Blocked by

- None. This is the first issue; everything in WS1 and WS5 depends on it.

## Verification-command

```
pytest tests/test_env_loading.py tests/test_bootstrap_key_shape.py -q
```
