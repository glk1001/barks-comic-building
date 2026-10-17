# `uv run` re-syncs the project before every command, and any dependency uv cannot
# resolve from disk or its content-addressed cache — a direct URL, an out-of-date
# lock — is revalidated over the network. That makes recipes fail with no connection
# even when the command itself needs nothing. UV_OFFLINE=1 short-circuits the check and
# runs from the already-installed venv. Go online after adding or changing a dependency,
# when the sync genuinely has to reach the network:
#
#     UV_OFFLINE=0 just build 9
#
# barks-ocr and barks-compleat-reader load this file as their `comics` module
# (`just comics build 9` from either repo) and export the same default, so one
# environment variable reaches every recipe whichever repo it is run from.
export UV_OFFLINE := env("UV_OFFLINE", "1")

uv_run := "uv run --project " + source_dir()

barks_dir            := "$HOME/Books/Carl Barks"
internal_2tb         := "/mnt/2tb_drive"
restore_work_dir     := internal_2tb + "/workdir/barks-restore"
regression_tests_dir := internal_2tb + "/Books/Carl Barks/Regression-Tests"

_default:
    @just --list --unsorted

# Get Fanta volume page and status info
[group('comics')]
info volume:
    {{uv_run}} barks-fanta-info --log-level WARNING --volume {{volume}}

# Get one-pager build state (all one-pagers, or just one volume's)
[group('comics')]
one-pager-info volume="":
    {{uv_run}} barks-one-pager-info --log-level WARNING --volume "{{volume}}"

# Get cover configured state (all covers, or just one volume's)
[group('comics')]
cover-info volume="":
    {{uv_run}} barks-cover-info --log-level WARNING --volume "{{volume}}"

# Get title page counts for Fanta volume or volumes
[group('comics')]
page-count volume:
    {{uv_run}} barks-fanta-story-page-count --log-level WARNING --volume {{volume}}

# Build a volume or volumes
[group('comics')]
build volume:
    {{uv_run}} barks-build --log-level INFO --volume "{{volume}}"

# Build a title
[group('comics')]
build-title title:
    {{uv_run}} barks-build --log-level INFO --title "{{title}}"

# Check the integrity of a volume or volumes
[group('comics')]
check-volume volume *flags:
    {{uv_run}} barks-check-build --log-level SUCCESS --volume "{{volume}}" {{flags}}

# Check the integrity of a title
[group('comics')]
check-title title *flags:
    {{uv_run}} barks-check-build --log-level SUCCESS --title "{{title}}" {{flags}}

# Check the censorship csv integrity
[group('comics')]
check-censorship-csv:
    {{uv_run}} barks-check-build --log-level SUCCESS --censorship-only

# Rename stale built artifacts onto their current chronological numbers instead of rebuilding (dry run: pass --apply to rename)
[group('comics')]
fix-names *flags:
    {{uv_run}} barks-check-build --log-level WARNING --fix-names {{flags}}

# Upscayl all restoreable pages in a volume or volumes
[group('comics')]
upscayl volume:
    {{uv_run}} barks-batch-upscayl --volume {{volume}}

# Upscayl all restoreable pages in a title
[group('comics')]
upscayl-title title:
    {{uv_run}} barks-batch-upscayl --title "{{title}}"

# Show what the upscale has done and what is left, per volume, with an estimate
[group('comics')]
upscale-status volume *flags:
    {{uv_run}} barks-upscale-status --volume {{volume}} {{flags}}

# List the pages whose last upscale attempt failed, and why
[group('comics')]
upscale-failures:
    {{uv_run}} barks-upscale-status --failed

# Restore all restoreable pages in a volume or volumes
[group('comics')]
restore volume:
    {{uv_run}} barks-batch-restore --work-dir {{restore_work_dir}}/restore --volume {{volume}}

# Resume a volume restore
[group('comics')]
restore-resume volume:
    {{uv_run}} barks-batch-restore --work-dir {{restore_work_dir}}/restore --volume {{volume}} --use-existing-work-files

# Restore all restoreable pages in a title
[group('comics')]
restore-title title:
    {{uv_run}} barks-batch-restore --work-dir {{restore_work_dir}}/restore --title "{{title}}"

# Ask a running restore to stop once the pages already under way have finished
[group('comics')]
restore-stop:
    {{uv_run}} barks-restore-stop --work-dir {{restore_work_dir}}/restore

# Ask a running restore to stop sooner, after each worker finishes its current step
[group('comics')]
restore-stop-now:
    {{uv_run}} barks-restore-stop --work-dir {{restore_work_dir}}/restore --now

# Take back a stop request and let the run carry on
[group('comics')]
restore-stop-cancel:
    {{uv_run}} barks-restore-stop --work-dir {{restore_work_dir}}/restore --withdraw

# Show what the restore has done and what is left, per volume, with an estimate
[group('comics')]
restore-status volume *flags:
    {{uv_run}} barks-restore-status --volume {{volume}} {{flags}}

# List the pages whose last restore attempt failed, and the step they failed at
[group('comics')]
restore-failures:
    {{uv_run}} barks-restore-status --failed

# Generate panel bounds for all restoreable pages in a volume or volumes
[group('comics')]
panels volume *flags:
    {{uv_run}} barks-batch-panel-bounds --work-dir {{restore_work_dir}}/panel-bounds --volume {{volume}} {{flags}}

# Generate panel bounds for all restoreable pages in a title
[group('comics')]
panels-title title *flags:
    {{uv_run}} barks-batch-panel-bounds --work-dir {{restore_work_dir}}/panel-bounds --title "{{title}}" {{flags}}

# Quickly browse a volume page
[group('utils')]
show-volume volume page:
    {{uv_run}} barks-show-volume-page --log-level WARNING --volume "{{volume}}" --page "{{page}}"

# Quickly browse a title page
[group('utils')]
show-title title page="1":
    {{uv_run}} barks-show-title-page --log-level WARNING --title "{{title}}" --page "{{page}}"

# Quickly edit a volume panel
[group('utils')]
edit-volume volume type page-panel:
    {{uv_run}} barks-edit-page --log-level WARNING --volume "{{volume}}" --type {{type}} --p-p {{page-panel}}

# Quickly edit a title panel from a volume page number
[group('utils')]
edit-title title type page-panel:
    {{uv_run}} barks-edit-page --log-level WARNING --title "{{title}}" --type {{type}} --p-p {{page-panel}}

# Quickly edit a title panel from a comic page number
[group('utils')]
edit-comic title type comic-page-panel:
    {{uv_run}} barks-edit-page --log-level WARNING --title "{{title}}" --type {{type}} --cp-p {{comic-page-panel}}

# Show panel bounds
[group('utils')]
show-panel-bounds volume page:
    {{uv_run}} barks-show-panel-bounds -- --log-level WARNING --volume "{{volume}}" --fanta-page "{{page}}"

# Verify/Find a title
[group('utils')]
verify-title title:
    {{uv_run}} barks-verify-title --log-level WARNING --title "{{title}}"

# Make empty config files for all restoreable pages in a volume or volumes
[group('comics')]
make-empty-configs volume:
    {{uv_run}} barks-make-empty-configs --log-level INFO --volume {{volume}}

# Show any differences between Fanta original pages and added pages for a volume or volumes
[group('comics')]
show-diffs volume:
    {{uv_run}} barks-show-fixes-diffs --log-level INFO --volume {{volume}}

# Do a small build test
[group('comics')]
test-small:
    scripts/small-build-test.sh "{{regression_tests_dir}}/Small/aaa-Chronological-dirs"
    {{uv_run}} scripts/compare_build_root_dirs.py \
               "{{regression_tests_dir}}/Small/aaa-Chronological-dirs" \
               "{{barks_dir}}/The Comics/aaa-Chronological-dirs"

# Compare all build files (or just the one for 'title') to the last known good build files
[group('comics')]
compare-all title="":
    {{uv_run}} scripts/compare_build_root_dirs.py --title "{{title}}" \
               "{{regression_tests_dir}}/Big/aaa-Chronological-dirs" \
               "{{barks_dir}}/The Comics/aaa-Chronological-dirs"

# Shortlist pages to eyeball for upscayl errors (regional compare, see docs/image-compare-cutoffs.md)
[group('comics')]
check-for-upscayl-errors volume:
    {{uv_run}} scripts/compare_fanta_image_dirs.py --volume "{{volume}}" \
               --diff-dir "/tmp/upscayl-diffs" --fuzz 20% \
               --tile-size 512 --tile-cutoff-pct 2 --log-level INFO

# Do a big image compare of restored to original looking for obvious changes
[group('comics')]
compare-restored-orig volume:
    {{uv_run}} scripts/compare_fanta_image_dirs.py --volume "{{volume}}" \
               --fuzz 50% --ae_cutoff 1000 --log-level INFO
