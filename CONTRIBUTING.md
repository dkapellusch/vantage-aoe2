# Contributing to Vantage

Thanks for your interest! Bug reports, ideas, translations and code are all welcome.

## Reporting bugs and asking questions

- Run `vantage doctor` first; it catches most setup problems.
- Open an [issue](https://github.com/dkapellusch/vantage/issues) with what you did, what you
  expected and what happened, plus the `vantage doctor` output and any browser console errors.
- Questions and ideas are best in [Discussions](https://github.com/dkapellusch/vantage/discussions).
- Security problems: see [SECURITY.md](SECURITY.md); please don't open a public issue.

## Development setup

You need [uv](https://docs.astral.sh/uv/), Python 3.12+ and (for the UI tests) Node.js 20+.

```sh
git clone https://github.com/dkapellusch/vantage
cd vantage
uv sync                       # creates .venv with the dev tools
uv run vantage serve --open   # run from source
```

Before sending a change, all four must pass (CI runs them on Linux and Windows):

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

[docs/development.md](docs/development.md) covers the project layout, the test suite, regenerating
the gRPC stubs and the release checklist. [docs/architecture.md](docs/architecture.md) explains how
the pieces fit together.

## Guidelines

- **Keep pull requests focused.** One fix or feature per PR is much easier to review. For larger
  changes, open an issue first so we can agree on the approach.
- **Tests.** New Python behaviour comes with focused, deterministic, offline tests in
  `tests/test_<module>.py`. UI logic that can run outside the browser has Node tests in
  `tests/*.test.mjs`.
- **Style.** Full type hints (mypy runs in strict mode), ruff-formatted, 100 columns. Comments explain
  *why*, not *what*. The web UI is plain ES modules with no build step; keep it that way.
- **Dependencies.** The runtime depends only on `grpcio` and `protobuf`. Please discuss before adding
  another runtime dependency.
- **User-facing text** goes through `t()` and its English source string is added to
  `src/vantage/web/i18n/_source_extra2.json`; see the [Translations](docs/wiki/Translations.md) page.
- **Changelog.** Note user-visible changes under "Unreleased" in [CHANGELOG.md](CHANGELOG.md).

## What we can't accept

- Game assets (graphics, sounds, strings) copied from Age of Empires II. Vantage reads them from the
  user's own installation at runtime.
- Certificates or keys of any kind, and instructions for obtaining the game API's client
  certificate.
- Code copied from other projects whose licence doesn't allow it, or code derived from decompiling
  the game or other software.
- Recordings or replays of other people's games as test fixtures, unless they agreed to it.

## Translations

Vantage's interface is translated into 16 languages. Corrections and new languages are very welcome;
see the [Translations](docs/wiki/Translations.md) page for how the files are organised.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be kind.

By contributing you agree that your contributions are licensed under the [MIT licence](LICENSE).
