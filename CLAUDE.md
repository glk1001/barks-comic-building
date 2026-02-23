# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`barks-comic-building` is a hatchling-backed Python package for processing, restoring, upscaling, and building CBZ archives of the Fantagraphics Carl Barks comic library. It is the build pipeline that produces the comic image files consumed by `barks-compleat-reader`.

## Commands

**Run an entry point:**
```bash
uv run barks-fanta-info --help
uv run barks-build --help
uv run barks-batch-restore --help
```

**Install the package (after any change to pyproject.toml):**
```bash
uv sync
```

**Common tasks via just:**
```bash
just build-title "title name"
just build-volume 1
just check-title "title name"
just restore volume
just upscayl volume
just panels volume
```

**Type-check (ty):**
```bash
uv run ty check
```

**Lint (ruff):**
```bash
uv run ruff check .
uv run ruff format .
```

## Architecture

### Package Structure

All live code is in `src/barks_comic_building/` as a proper installable hatchling package. Entry points are registered in `[project.scripts]` in `pyproject.toml`. The old flat directories (`barks-cmds/`, `build-comics/`, `barks-restore/`, `barks-restore/src/`) are kept as dead code and excluded from linting and type checking.

| Subpackage | Entry points | Role |
|---|---|---|
| `query/` | 19 (`barks-fanta-info`, `barks-build`, etc.) | CLI scripts for querying and browsing comic metadata |
| `build/` | 2 (`barks-build`, `barks-check-build`) | Comic assembly — builds CBZ archives from restored/upscaled pages |
| `restore/` | 7 (`barks-batch-restore`, `barks-batch-upscayl`, etc.) | Image restoration and upscaling pipeline |

### Shared Modules

- `src/barks_comic_building/log_setup.py` — shared loguru-config globals (`APP_LOGGING_NAME`, `log_level`, `log_filename`). Each CLI script sets these before calling `LoguruConfig.load(_RESOURCES / "log-config.yaml")`.
- `src/barks_comic_building/resources/log-config.yaml` — centralized log config referenced via `ext://barks_comic_building.log_setup.*`.

### Shared Packages

Three shared packages from `barks-compleat-reader` are installed as editable **uv path dependencies** — no `PYTHONPATH` needed:

| Package | Role |
|---|---|
| `barks_fantagraphics` | Comics database, titles, pages, metadata |
| `barks_build_comic_images` | Image building utilities |
| `comic_utils` | Shared low-level utilities (image I/O, CLI options, etc.) |

Path dependencies are declared in `pyproject.toml` under `[tool.uv.sources]` pointing to `../barks-compleat-reader/src/`.

## Code Style

- Python 3.13+ syntax.
- Type hints required on all function signatures; use `str | None` not `Optional[str]`.
- Formatter: `ruff` (line length 100, config in `.ruff.toml`).
- Type checker: `ty` (config in `ty.toml`).
- Old flat directories (`barks-cmds/`, `build-comics/`, `barks-restore/`, `barks-restore/src/`, `scripts/`) are excluded from linting and type checking.
- `src/barks_comic_building/query/silent_night_panel_restore.py` is excluded from type checking.
