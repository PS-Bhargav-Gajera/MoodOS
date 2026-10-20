# AGENTS.md

## Rules

- Tests must not touch data/*.db.
  `tests/conftest.py` redirects `settings.sqlite_path` to a temp file at import
  time, so module-level `init_db()` calls are covered too. Individual tests that
  write rows should additionally point `settings.sqlite_path` at their own
  `tmp_path` so they stay isolated when run alone.
- Tests must not touch data/spotify_tokens.json.
  `tests/conftest.py` redirects `spotify.TOKEN_PATH` to a temp file for the same
  reason: `spotify._save_user()` writes it unconditionally, so a test covering
  the OAuth exchange or scope detection would clobber the developer's live
  Spotify session. Tests that rewrite the token should point `TOKEN_PATH` at
  their own `tmp_path` so they stay isolated when run alone.
