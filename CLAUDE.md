# CLAUDE.md

## Project Overview

`barks-comic-building` is a hatchling-backed Python package for processing, restoring, upscaling, and building CBZ archives of the Fantagraphics Carl Barks comic library. It is the build pipeline that produces the comic image files consumed by `barks-compleat-reader`.

Run `uv sync` after any change to `pyproject.toml`.

## Architecture

### Shared Modules

- `src/barks_comic_building/log_setup.py` — shared loguru-config globals (`APP_LOGGING_NAME`, `log_level`, `log_filename`). Each CLI script sets these before calling `LoguruConfig.load(_RESOURCES / "log-config.yaml")`.
- `src/barks_comic_building/resources/log-config.yaml` — centralized log config referenced via `ext://barks_comic_building.log_setup.*`.

### Shared Packages

The shared packages from `barks-compleat-reader` are installed as editable **uv path dependencies** (declared in `pyproject.toml` under `[tool.uv.sources]`) — no `PYTHONPATH` needed.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
