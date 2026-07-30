#!/bin/bash
# On-demand pyrefly run. pyrefly is a GATE (pre-commit, full-lint.sh) run alongside
# ty; this script is just the convenience entry point, and passes any extra flags
# straight through:
#     bash scripts/pyrefly.sh                     # the gate: expect "0 errors"
#     bash scripts/pyrefly.sh --min-severity=warn # also show the non-gating warnings
#     bash scripts/pyrefly.sh src/barks_comic_building/restore  # just one subtree
#
# The gate is a plain 0 errors and there is deliberately no baseline file here (see
# pyrefly.toml), so there is nothing to refresh after a fix - a clean run is a pass.

set -uo pipefail

cd "$(dirname "$0")/.."

echo "==== pyrefly ===="
uv run pyrefly check --progress-bar=no "$@"
