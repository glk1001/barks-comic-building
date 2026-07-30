#!/bin/bash
# Run every lint/static check over the whole repo, in one go.
# All checks run even if an earlier one fails; a summary is printed at the end.
#
# Checks: ruff check, ruff format (--check, so it reports rather than rewrites),
#         ty (--error-on-warning, matching the pre-commit hook), pyrefly (0 errors,
#         no baseline - see pyrefly.toml), cspell, deptry (unused/missing/misplaced
#         dependencies, configured under [tool.deptry] in pyproject.toml).
# Non-gating: uv audit (dependency CVEs) warns but never fails the run.
#
# Static checks only - this does not run the test suite. For that: uv run pytest

set -uo pipefail

cd "$(dirname "$0")/.."

declare -a failed=()
declare -a warned=()

run_check() {
    local name="$1"
    shift

    echo
    echo "==== ${name} ===="
    if ! "$@"; then
        failed+=("$name")
    fi
}

# Non-gating check: run it and surface the result, but never fail the run. Used for
# uv audit, whose advisory DB changes daily (a new upstream CVE could turn a passing
# tree red with no local change), so it warns rather than blocks.
run_warn() {
    local name="$1"
    shift

    echo
    echo "==== ${name} (warning only) ===="
    if ! "$@"; then
        warned+=("$name")
    fi
}

run_check "ruff check"   uv run ruff check .
run_check "ruff format"  uv run ruff format --check .
run_check "ty"           uv run ty check . --error-on-warning
run_check "pyrefly"      uv run pyrefly check --progress-bar=no
run_check "cspell"       bunx cspell --no-progress --no-must-find-files
run_check "deptry"       uv run deptry .
run_warn  "uv audit"     uv audit --preview-features audit-command

echo
echo "===================="
if [[ ${#warned[@]} -ne 0 ]]; then
    echo "WARNINGS (non-gating): ${warned[*]}"
fi
if [[ ${#failed[@]} -eq 0 ]]; then
    echo "All lint checks passed."
else
    echo "FAILED checks: ${failed[*]}"
    exit 1
fi
