# Repository Guidelines

## Project Structure & Module Organization

`faildns.py` is the main executable script. It contains DNS response logic, logging, CLI parsing, and asyncio server code.

Tests live in `tests/`:

- `tests/test_faildns_unit.py` covers response construction and helper behavior.
- `tests/test_faildns_integration.py` starts the script on loopback ports and tests UDP/TCP behavior.

Operational files are at the repository root: `faildns.service`, `faildns.default`, `Makefile`, and `pyproject.toml`/`uv.lock`.

## Build, Test, and Development Commands

- `sudo apt install python3-dnspython`: install the production runtime dependency on Debian.
- `python3 ./faildns.py`: run locally with system Python.
- `make dev`: create or update the uv environment for ad hoc runs and development tools.
- `uv run ./faildns.py`: run through the uv-managed environment.
- `make format`: format with Ruff.
- `make lint`: lint with Ruff.
- `make test`: run all unit and integration tests with system `python3`.
- `make uv-test`: run all tests in the uv-managed environment; use `DNSPYTHON=2.3.0`, `2.7.0`, `2.8.0`, or `latest-2.x` when matching CI variants.
- `make check`: run lint, syntax check, and tests.
- `sudo make install`: install the script to `/usr/local/bin/faildns` plus systemd and default-env files.

## Coding Style & Naming Conventions

Use Python 3.11-compatible code and 4-space indentation. Keep functions small and explicit. Use `snake_case` for functions, variables, and test names; use uppercase for constants such as `DEFAULT_SERVFAIL_PORT`.

Ruff is the formatter and linter. Do not add broad abstractions unless they simplify the single-script design.

## Testing Guidelines

The test framework is stdlib `unittest`. Add unit tests for pure response logic and integration tests for socket-level behavior. Name tests `test_<behavior>`.

Integration tests bind loopback ports and may need normal local socket permissions. Production-oriented tests default to system `python3`; use `PYTHON=.venv/bin/python make test` to test the uv environment.

## Commit & Pull Request Guidelines

Use short imperative commit subjects, for example `Add dnsdist healthcheck response`.

Agent-local commit rules: commit bodies must use point-form bullets only, focused on functional changes such as behavior, bug fixes, or refactor intent. Skip tests, lint, formatting, and coverage. Do not add marketing language or emoji. Run `make lint` before committing.

Pull requests should include a concise summary, the test command run, and any operational impact for Debian/systemd users.

## Security & Configuration Tips

The default listen address is `127.0.0.1`. Use `0.0.0.0` only when remote clients are expected. Keep production dependency management tied to Debian packages; uv is for ad hoc development support.
