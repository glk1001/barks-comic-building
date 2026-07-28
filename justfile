uv_run := "uv run --project " + source_dir()

rsync_flags := ""
rsync_dirs := "rsync --delete -avh " + rsync_flags

barks_dir := "$HOME/Books/Carl Barks"

# @formatter:off
# Base drive mount points
internal_2tb          := "/mnt/2tb_drive"
external_2tb_backup_1 := "/run/media/greg/2tb_drive_backup"
external_2tb_backup_2 := "/run/media/greg/2tb_drv_backup_2"
external_2tb_backup_3 := "/run/media/greg/2tb_drv_backup_3"
external_1tb_backup_1 := "/run/media/greg/1TB_Backup_1"
external_1tb_backup_2 := "/run/media/greg/1TB_Backup_2/home-rsync-backup"
external_1tb_backup_3 := "/run/media/greg/1TB_Backup_3/home-rsync-backup"
external_750          := "/run/media/greg/750_Backup"
external_500_1        := "/run/media/greg/500_Backup_1"
external_500_2        := "/run/media/greg/500_Backup_2"
external_music        := "/run/media/greg/MusicBarksBackup"
external_restic       := "/run/media/greg/restic_backup"
external_root         := "/run/media/greg/root_backup"

# Source directories
barks_wiki_dir          := "$HOME/Prj/github/barks-compleat-digital/barks-wiki"
barks_reader_config_dir := "$HOME/opt/barks-reader/config"
fast_data_dir           := "/mnt/fast_data"
fast_external_dir       := "/mnt/fast_external"
# @formatter:on

internal_2tb_exclude_dirs := "--exclude workdir/ --exclude lost+found/ --exclude 'VirtualBox VMs/VMs/WinDev2202Eval'"
internal_1tb_exclude_dirs := "--exclude greg/.cache/ --exclude greg/.local/share/Trash/ " \
                             + "--exclude greg/.gvfs/ --exclude greg/.dbus/ --exclude lost+found/"
restore_work_dir          := internal_2tb + "/workdir/barks-restore"
regression_tests_dir      := internal_2tb + "/Books/Carl Barks/Regression-Tests"
home_dir                  := "/home"

_default:
    just --list --unsorted | tee /tmp/junk.log

show-vars:
    @pwd
    @echo 'this source_dir = "{{source_dir()}}"'
    @echo 'calling justfile = "{{justfile()}}"'

show-env:
    env


# Get Fanta volume page and status info
[group('comics')]
info volume:
    {{uv_run}} barks-fanta-info --log-level WARNING --volume {{volume}}

# Get title page counts for Fanta volume or volumes
[group('comics')]
page-count volume:
    {{uv_run}} barks-fanta-story-page-count --log-level WARNING --volume {{volume}}

# Build a title
[group('comics')]
build-title title:
    {{uv_run}} barks-build --log-level INFO --title "{{title}}"

# Build a volume or volumes
[group('comics')]
build-volume volume:
    {{uv_run}} barks-build --log-level INFO --volume "{{volume}}"

# Check the integrity of a title
[group('comics')]
check-title title *flags:
    {{uv_run}} barks-check-build --log-level WARNING --title "{{title}}" {{flags}}

# Check the integrity of a volume or volumes
[group('comics')]
check-volume volume *flags:
    {{uv_run}} barks-check-build --log-level WARNING --volume "{{volume}}" {{flags}}

# Rename stale built artifacts onto their current chronological numbers, instead of
# rebuilding them. Dry run: pass --apply to actually perform the renames.
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

# Restore all restoreable pages in a volume or volumes
[group('comics')]
restore volume:
    {{uv_run}} barks-batch-restore --work-dir {{restore_work_dir}}/restore --volume {{volume}}

# Restore all restoreable pages in a title
[group('comics')]
restore-title title:
    {{uv_run}} barks-batch-restore --work-dir {{restore_work_dir}}/restore --title "{{title}}"

# Generate panel bounds for all restoreable pages in a volume or volumes
[group('comics')]
panels volume:
    {{uv_run}} barks-batch-panel-bounds --work-dir {{restore_work_dir}}/panel-bounds --volume {{volume}}

# Generate panel bounds for all restoreable pages in a title
[group('comics')]
panels-title title:
    {{uv_run}} barks-batch-panel-bounds --work-dir {{restore_work_dir}}/panel-bounds --title "{{title}}"

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
    bash scripts/small-build-test.sh
    {{uv_run}} scripts/compare_build_root_dirs.py \
               "{{regression_tests_dir}}/Small/aaa-Chronological-dirs" \
               "{{barks_dir}}/The Comics/aaa-Chronological-dirs"

# Compare all build files to the last known good build files
[group('comics')]
compare-all:
    {{uv_run}} scripts/compare_build_root_dirs.py \
               "{{regression_tests_dir}}/Big/aaa-Chronological-dirs" \
               "{{barks_dir}}/The Comics/aaa-Chronological-dirs"

# Do a big image compare of restored to original looking for upscayl errors
[group('comics')]
check-for-upscayl-errors volume:
    {{uv_run}} scripts/compare_fanta_image_dirs.py "{{barks_dir}}/Fantagraphics-restored" \
                                                   "{{barks_dir}}/Fantagraphics-original" \
                                                   "/tmp/upscayl-diffs" \
                                                   --volume {{volume}} --fuzz 50% --ae_cutoff 10000

# Do a big image compare of restored to original looking for obvious changes
[group('comics')]
compare-restored-orig volume:
    {{uv_run}} scripts/compare_fanta_image_dirs.py "{{barks_dir}}/Fantagraphics-restored" \
                                                   "{{barks_dir}}/Fantagraphics-original" 50% 5000 {{volume}}

# Rsync root drive to 'root' external drive
[group('rsync')]
backup-to-root-external:
    sudo rsync -aAXv --delete \
        --exclude='/dev/*' \
        --exclude='/proc/*' \
        --exclude='/sys/*' \
        --exclude='/tmp/*' \
        --exclude='/run/*' \
        --exclude='/mnt/*' \
        --exclude='/media/*' \
        --exclude='/lost+found' \
        --exclude='/var/cache/*' \
        --exclude='/var/tmp/*' \
        --exclude='/snap/*' \
        --exclude='/var/lib/snapd/void' \
        --exclude='/var/lib/snapd/cache/*' \
        --exclude='/var/lib/snapd/cookie' \
        --exclude='/root/.cache/*' \
        --exclude='/home/*' \
        / "{{external_root}}/"

# Rsync 2tb internal drive to the main 2tb external backup drive
[group('rsync')]
[confirm]
backup-to-2tb-external-1:
    {{rsync_dirs}} {{internal_2tb_exclude_dirs}} "{{internal_2tb}}/" "{{external_2tb_backup_1}}/"

# Rsync 2tb internal drive to the 2tb external backup drive no. 2
[group('rsync')]
backup-to-2tb-external-2:
    {{rsync_dirs}} {{internal_2tb_exclude_dirs}} "{{internal_2tb}}/" "{{external_2tb_backup_2}}/"

# Rsync 2tb internal drive to the 2tb external backup drive no. 3
[group('rsync')]
backup-to-2tb-external-3:
    {{rsync_dirs}} {{internal_2tb_exclude_dirs}} "{{internal_2tb}}/" "{{external_2tb_backup_3}}/"

# Rsync 1tb home internal drive to the 1tb external backup drive no. 1
[group('rsync')]
backup-home-to-1tb-external-1:
    {{rsync_dirs}} -x {{internal_1tb_exclude_dirs}} "{{home_dir}}/" "{{external_1tb_backup_1}}/"

# Rsync 1tb home internal drive to the 1tb external backup drive no. 2
[group('rsync')]
backup-home-to-1tb-external-2:
    {{rsync_dirs}} -x {{internal_1tb_exclude_dirs}} "{{home_dir}}/" "{{external_1tb_backup_2}}/"

# Rsync 1tb home internal drive to the 1tb external backup drive no. 3
[group('rsync')]
backup-home-to-1tb-external-3:
    {{rsync_dirs}} -x {{internal_1tb_exclude_dirs}} "{{home_dir}}/" "{{external_1tb_backup_3}}/"

# Rsync all Barks files to the 2tb internal drive
[group('rsync')]
backup-to-2tb-internal:
    {{rsync_dirs}} "{{barks_dir}}/"               "{{internal_2tb}}/barks-backup/Carl Barks/"
    {{rsync_dirs}} "{{barks_wiki_dir}}/"          "{{internal_2tb}}/barks-backup/barks-wiki/"
    {{rsync_dirs}} "{{barks_reader_config_dir}}/" "{{internal_2tb}}/barks-backup/barks-reader-config/"

# Rsync all Barks files FROM the main 2tb external backup drive
[group('rsync')]
[confirm]
backup-from-2tb-external:
    {{rsync_dirs}} {{internal_2tb_exclude_dirs}} \
                   "{{external_2tb_backup_1}}/"                         "{{internal_2tb}}/"
    {{rsync_dirs}} "{{internal_2tb}}/barks-backup/Carl Barks/"          "{{barks_dir}}/"
    {{rsync_dirs}} "{{internal_2tb}}/barks-backup/barks-wiki/"          "{{barks_wiki_dir}}/"
    {{rsync_dirs}} "{{internal_2tb}}/barks-backup/barks-reader-config/" "{{barks_reader_config_dir}}/"

# Rsync all Barks files to the '750_Backup' external backup drive
# Not sustainable - almost reached limit.
[group('rsync')]
backup-to-750-external:
    {{rsync_dirs}} "{{barks_dir}}/"          "{{external_750}}/barks-backup/Carl Barks/"
    {{rsync_dirs}} "{{barks_wiki_dir}}/"     "{{external_750}}/barks-backup/barks-wiki/"
    {{rsync_dirs}} "{{internal_2tb}}/Books/" "{{external_750}}/Books/"

# Rsync fast_data and fast_external to '500_backup_1' external backup drive
[group('rsync')]
backup-to-500-external-1:
    {{rsync_dirs}} --exclude lost+found/ "{{fast_data_dir}}/"     "{{external_500_1}}/fast_data_backup/"
    {{rsync_dirs}} --exclude lost+found/ "{{fast_external_dir}}/" "{{external_500_1}}/fast_external_backup/"

# Rsync fast_data and fast_external to '500_backup_2' external backup drive
[group('rsync')]
backup-to-500-external-2:
    {{rsync_dirs}} --exclude lost+found/ "{{fast_data_dir}}/"     "{{external_500_2}}/fast_data_backup/"
    {{rsync_dirs}} --exclude lost+found/ "{{fast_external_dir}}/" "{{external_500_2}}/fast_external_backup/"

# Rsync all Barks files to the 'music' external drive
[group('rsync')]
backup-to-music-external:
    {{rsync_dirs}} "{{barks_dir}}/" "{{external_music}}/Books/Carl Barks/"

# Rsync all Barks files to the 'restic' external drive
[group('rsync')]
backup-to-restic-external:
    {{rsync_dirs}} "{{barks_dir}}/" "{{external_restic}}/Books/Carl Barks/"
