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

**Run every static check at once** (ruff check + format, ty, pyrefly, cspell, deptry; plus `uv audit` as a non-gating warning):

```bash
bash scripts/full-lint.sh
```

It does not run the tests — use `uv run pytest` for those.

**Toolchain bump.** `ruff` and `ty` are `==`-pinned; bump them deliberately on a branch with `bash scripts/bump-toolchain.sh`, which re-locks, re-syncs and runs every gate without committing or pushing. Runbook: `../barks-compleat-reader/docs/toolchain-bump.md`.

**Type-check (two checkers).** `ty` is the primary; **pyrefly** is gated alongside it and is stricter on nullability, which is most of what it earns us. Config and rationale live in `pyrefly.toml`.

```bash
uv run ty check . --error-on-warning
bash scripts/pyrefly.sh                      # or: uv run pyrefly check
bash scripts/pyrefly.sh --min-severity=warn  # also show the non-gating warnings
```

The pyrefly gate is a plain **0 errors** with **no baseline file** — unlike the sibling `barks-compleat-reader`, this project has no Kivy-boundary noise worth grandfathering. Keep it that way: fix a new finding, or suppress it at the line with a `# pyrefly: ignore[<rule>]` comment saying why, rather than adding a baseline to hide it. The only suppressions today are the deliberately dynamic `dataclasses.replace(recipe, **{field: changed})` in the two recipe tests, explained in place. `comics_integrity.py` used to carry a tuple-variance hit as well (a `Path | zipfile.Path` reaching a `Path` slot, suppressed for both checkers); it went away by narrowing at the point of production instead — `walk_srce_dependency_chain` in `build/utils.py` handles the `zipfile.Path` case explicitly, so the union never reaches the reporting end. That also removed the bare `assert isinstance(...)` that had been standing in for the narrowing 380 lines away. `cv2` is treated as `Any` via config, matching ty's effective stance on its missing stubs.

pyrefly also has a **warning** severity below the gated errors, hidden unless you pass `--min-severity=warn`. It is currently clean there too; `types-python-dateutil` and `types-psutil` are dev dependencies purely to keep it that way.

**Dependencies (deptry).** `uv run deptry .` reports imports that are not declared, declarations that are not imported, and direct use of transitive dependencies. Config is under `[tool.deptry]` in `pyproject.toml`.

The thing to know when triaging a DEP002 ("declared but not imported"): the shared `barks-*`/`comic-utils` path dependencies **under-declare their own requirements** — `comic-utils` declares none at all — so this project's `pyproject.toml` is what actually installs some of what they import at runtime. `distro`, `pyyaml` and `screeninfo` are all in that position and are ignored for DEP002 with the import chain written out.

So a DEP002 is not automatically a dependency to delete. Check whether anything here **reaches** it first; if it does, ignore the rule and record the chain. `cryptography` was the counter-example — it was carried for `comic_utils.get_panel_bytes`, but that only decrypts images out of a cbz, which is the reader's job and unreachable from here, so it was removed rather than ignored.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
