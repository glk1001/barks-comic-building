#!/bin/bash
# Monthly toolchain bump: move ruff/ty/pyrefly forward on a branch, run every gate,
# and report. Nothing is committed and nothing is pushed - you inspect the branch and
# decide.
#
# Why this exists: ruff and ty are pinned with `==` in pyproject.toml (see the
# comments there). That is deliberate - with `select = ["ALL"]` a ruff release can
# change our lint policy, and ty is a 0.0.x beta that has shipped a flaky panic
# before. But a pin you never revisit is just staleness, so this script makes the
# bump a scheduled, reviewable event rather than something that ambushes an
# unrelated commit. Run it on the 1st of the month; see the runbook at
# ../barks-compleat-reader/docs/toolchain-bump.md (canonical for all three barks repos).
#
#     bash scripts/bump-toolchain.sh                # bump ruff, ty and pyrefly
#     bash scripts/bump-toolchain.sh ruff           # just one tool
#     bash scripts/bump-toolchain.sh --no-branch    # bump in place, no branch
#
# Requires a clean working tree (it refuses otherwise, so the bump diff stays
# reviewable on its own) plus curl and python3 for the PyPI version lookup.

set -uo pipefail

cd "$(dirname "$0")/.."

MAKE_BRANCH=1
declare -a TOOLS=()

for arg in "$@"; do
    case "$arg" in
        --no-branch) MAKE_BRANCH=0 ;;
        -*)
            echo "ERROR: unknown flag '$arg'." >&2
            exit 2
            ;;
        *) TOOLS+=("$arg") ;;
    esac
done

# Default set. pyrefly is here even though it is not `==`-pinned: `uv lock` will not
# move a transitive-free dev tool on its own, so it needs an explicit upgrade too.
if [[ ${#TOOLS[@]} -eq 0 ]]; then
    TOOLS=(ruff ty pyrefly)
fi

for cmd in git uv curl python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: '$cmd' is required but not on PATH." >&2
        exit 1
    fi
done

# Tracked files only: untracked scratch files cannot muddle the pyproject/uv.lock
# diff this script produces, so there is no reason to block on them.
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "ERROR: working tree has uncommitted changes to tracked files."
    echo "       Commit or stash first - the point of this script is a bump diff you"
    echo "       can review on its own, which a dirty tree would muddle."
    exit 1
fi

original_branch="$(git rev-parse --abbrev-ref HEAD)"

# Latest non-prerelease version on PyPI. `.info.version` skips pre-releases, which is
# what we want - a scheduled bump should not opt us into an alpha.
latest_version() {
    curl -fsSL "https://pypi.org/pypi/$1/json" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])'
}

# The version actually resolved in uv.lock, which is what the gates really run.
locked_version() {
    awk -v pkg="$1" '
        $0 == "name = \"" pkg "\"" { found = 1; next }
        found && /^version = / { gsub(/[",]/, "", $3); print $3; exit }
    ' uv.lock
}

declare -a upgrade_args=()
declare -a summary=()
changed=0

for tool in "${TOOLS[@]}"; do
    spec="$(grep -oE "\"${tool}(==|>=)[0-9][^\"]*\"" pyproject.toml | head -1)"
    if [[ -z "$spec" ]]; then
        summary+=("$tool: not a dependency of this repo - skipped")
        continue
    fi

    latest="$(latest_version "$tool")"
    if [[ -z "$latest" ]]; then
        summary+=("$tool: PyPI lookup FAILED - left alone")
        continue
    fi

    before="$(locked_version "$tool")"

    if [[ "$spec" == *"=="* ]]; then
        pinned="${spec#\"${tool}==}"
        pinned="${pinned%\"}"
        if [[ "$pinned" == "$latest" ]]; then
            summary+=("$tool: already at $latest (pinned)")
            continue
        fi
        # Rewrite the `==` pin in place; uv lock below makes it real.
        sed -i -E "s/\"${tool}==[0-9][^\"]*\"/\"${tool}==${latest}\"/" pyproject.toml
        summary+=("$tool: pin $pinned -> $latest")
        changed=1
    else
        if [[ "$before" == "$latest" ]]; then
            summary+=("$tool: already at $latest (floating)")
            continue
        fi
        upgrade_args+=(--upgrade-package "$tool")
        summary+=("$tool: floating $before -> $latest")
        changed=1
    fi
done

echo
echo "==== planned ===="
printf '  %s\n' "${summary[@]}"

if [[ $changed -eq 0 ]]; then
    echo
    echo "Nothing to bump - every requested tool is already current."
    exit 0
fi

if [[ $MAKE_BRANCH -eq 1 ]]; then
    branch="toolchain-bump-$(date +%Y-%m-%d)"
    if git show-ref --verify --quiet "refs/heads/$branch"; then
        echo "ERROR: branch '$branch' already exists - delete it or use --no-branch." >&2
        git checkout -- pyproject.toml
        exit 1
    fi
    echo
    echo "==== branching ===="
    git checkout -b "$branch" || exit 1
fi

echo
echo "==== uv lock ===="
if ! uv lock "${upgrade_args[@]+"${upgrade_args[@]}"}"; then
    echo "ERROR: uv lock failed. pyproject.toml has been left modified for inspection." >&2
    exit 1
fi

echo
echo "==== uv sync ===="
if ! uv sync; then
    echo "ERROR: uv sync failed. The lock has been left in place for inspection." >&2
    exit 1
fi

echo
echo "==== resolved ===="
for tool in "${TOOLS[@]}"; do
    v="$(locked_version "$tool")"
    [[ -n "$v" ]] && echo "  $tool $v"
done

echo
echo "==== gates ===="
lint_status=0
if [[ -f scripts/full-lint.sh ]]; then
    bash scripts/full-lint.sh
    lint_status=$?
else
    echo "No scripts/full-lint.sh in this repo - skipping the gate run." >&2
    lint_status=127
fi

echo
echo "===================="
printf '  %s\n' "${summary[@]}"
echo
if [[ $lint_status -eq 0 ]]; then
    echo "Gates PASSED. Review the diff, then commit if you are happy:"
    echo "    git diff pyproject.toml uv.lock"
elif [[ $lint_status -eq 127 ]]; then
    echo "Gates NOT RUN (no full-lint.sh). Bump applied; verify it by hand."
else
    echo "Gates FAILED. This is the bump's fallout - triage it here, not under an"
    echo "unrelated commit. Nothing was committed or pushed."
fi
echo
echo "Nothing has been committed or pushed."
if [[ $MAKE_BRANCH -eq 1 ]]; then
    echo "To abandon the bump:"
    echo "    git checkout $original_branch && git branch -D toolchain-bump-$(date +%Y-%m-%d)"
    echo "    git checkout -- pyproject.toml uv.lock   # if anything is left dirty"
fi

exit $lint_status
