#! /bin/bash

# Build every title that has a regression-test baseline, ready for
# 'compare_build_root_dirs.py' to diff the results against that baseline.
#
# The title list is derived from the baseline directory rather than hardcoded,
# so a title can never be built without being compared, or have a baseline that
# is never rebuilt.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $(basename "$0") <baseline-chronological-dirs>" >&2
    exit 1
fi

baseline_dir=$1

if [[ ! -d ${baseline_dir} ]]; then
    echo "Error: Could not find baseline directory: \"${baseline_dir}\"." >&2
    exit 1
fi

# Baseline dirs are named "<chronological number> <title>". Without nullglob an
# empty baseline dir would leave the glob unexpanded and "build" a title of "*".
shopt -s nullglob

titles=()
for dir in "${baseline_dir}"/*/; do
    dir_name=$(basename "${dir}")
    titles+=("${dir_name#* }")
done

if [[ ${#titles[@]} -eq 0 ]]; then
    echo "Error: No baseline titles in \"${baseline_dir}\"." >&2
    exit 1
fi

echo "Building ${#titles[@]} titles with a baseline in \"${baseline_dir}\"."

for title in "${titles[@]}"; do
    just build-title "${title}"
done
