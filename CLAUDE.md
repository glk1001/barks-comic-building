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

## Lint and type checking

Every gate runs the tool from the uv-synced venv, so the versions pinned in `pyproject.toml` are the single source of truth. All of them are wired into `.pre-commit-config.yaml`.

**Run every static check at once** (ruff check + format, ty, pyrefly, cspell; plus `uv audit` as a non-gating warning):

```bash
bash scripts/full-lint.sh
```

It does not run the tests — use `uv run pytest` for those.

**Type-check (two checkers).** `ty` is the primary; **pyrefly** is gated alongside it and is stricter on nullability, which is most of what it earns us. Config and rationale live in `pyrefly.toml`.

```bash
uv run ty check . --error-on-warning
bash scripts/pyrefly.sh                      # or: uv run pyrefly check
bash scripts/pyrefly.sh --min-severity=warn  # also show the non-gating warnings
```

The pyrefly gate is a plain **0 errors** with **no baseline file** — unlike the sibling `barks-compleat-reader`, this project has no Kivy-boundary noise worth grandfathering. Keep it that way: fix a new finding, or suppress it at the line with a `# pyrefly: ignore[<rule>]` comment saying why, rather than adding a baseline to hide it. Two suppressions exist today, both explained in place: the deliberately dynamic `dataclasses.replace(recipe, **{field: changed})` in the recipe tests, and a tuple-variance hit in `comics_integrity.py` that `ty` also ignores. `cv2` is treated as `Any` via config, matching ty's effective stance on its missing stubs.

pyrefly also has a **warning** severity below the gated errors, hidden unless you pass `--min-severity=warn`. It is currently clean there too; `types-python-dateutil` and `types-psutil` are dev dependencies purely to keep it that way.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
