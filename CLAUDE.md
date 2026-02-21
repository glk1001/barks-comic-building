# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`barks-comic-building` is a collection of scripts and tools for processing, restoring, upscaling, and building CBZ archives of the Fantagraphics Carl Barks comic library. It is the build pipeline that produces the comic image files consumed by `barks-compleat-reader`.

## Commands

**Run a script:**
```bash
uv run barks-cmds/fantagraphics-info.py --help
uv run build-comics/batch-build-comics.py --help
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
uvx ty check
```

**Lint (ruff):**
```bash
uv run ruff check .
uv run ruff format .
```

## Architecture

### Directory Structure

| Directory | Role |
|---|---|
| `barks-cmds/` | Standalone CLI scripts for querying and browsing comics metadata |
| `barks-restore/` | Image restoration and upscaling pipeline |
| `barks-restore/src/` | Internal Python package with restoration modules (`restore_pipeline`, `image_io`, `upscale_image`, etc.) |
| `build-comics/` | Comic assembly — builds CBZ archives from restored/upscaled pages |
| `scripts/` | Utility and comparison scripts |

### Shared Packages

The three shared packages from `barks-compleat-reader` are installed as editable **uv path dependencies** — no `PYTHONPATH` configuration needed:

| Package | Role |
|---|---|
| `barks_fantagraphics` | Comics database, titles, pages, metadata |
| `barks_build_comic_images` | Image building utilities |
| `comic_utils` | Shared low-level utilities (image I/O, CLI options, etc.) |

Path dependencies are declared in `pyproject.toml` under `[tool.uv.sources]` pointing to `../barks-compleat-reader/src/`.

### Internal Package Import Pattern

Scripts in `barks-restore/` import from `barks-restore/src/` using `from src.restore_pipeline import ...`. This works because Python adds the script's own directory to `sys.path` at runtime — no path configuration required.

## Code Style

- Python 3.13+ syntax.
- Type hints required on all function signatures; use `str | None` not `Optional[str]`.
- Formatter: `ruff` (line length 100, config in `.ruff.toml`).
- Type checker: `ty` (config in `ty.toml`).
- `barks-restore/experiments/` and `build-comics/scraps/` are excluded from linting and type checking.
