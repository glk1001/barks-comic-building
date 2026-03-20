uv_run := "uv run --project " + source_dir()

barks_dir := "$HOME/Books/Carl Barks"

barks_2tb_internal_backup_dir := "/mnt/2tb_drive/barks-backup/Carl Barks"
barks_2tb_external_backup_dir := "/media/greg/2tb_drive_backup/barks-backup/Carl Barks"
barks_2tb_internal_books_dir := "/mnt/2tb_drive/Books"
barks_2tb_external_books_dir := "/media/greg/2tb_drive_backup/Books"
barks_1tb_external_backup_dir := "/media/greg/1TB_Backup/barks-backup/Carl Barks"
barks_1tb_external_backup_big_dirs := "/media/greg/1TB_Backup/barks-backup/Carl Barks-big-dirs"
barks_1tb_external_backup_2_dir := "/media/greg/1TB_Backup_2/barks-backup/Carl Barks"
barks_1tb_external_backup_2_big_dirs := "/media/greg/1TB_Backup_2/barks-backup/Carl Barks-big-dirs"
barks_music_external_backup_dir := "/media/greg/MusicBarksBackup/Books/Carl Barks"
barks_restic_external_backup_dir := "/media/greg/restic_backup/Books/Carl Barks"
barks_750_external_backup_dir := "/media/greg/750_Backup/barks-backup/Books/Carl Barks"
barks_750_external_backup_big_dirs := "/media/greg/750_Backup/barks-backup/Carl Barks-big-dirs"

barks_reader_config_dir := "$HOME/opt/barks-reader/config"
barks_2tb_internal_barks_reader_config_backup_dir := "/mnt/2tb_drive/barks-reader-config"
barks_2tb_external_barks_reader_config_backup_dir := "/media/greg/2tb_drive_backup/barks-reader-config"

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
    {{uv_run}} barks-batch-restore --work-dir /mnt/2tb_drive/workdir/barks-restore/restore --volume {{volume}}

# Restore all restoreable pages in a title
[group('comics')]
restore-title title:
    {{uv_run}} barks-batch-restore --work-dir /mnt/2tb_drive/workdir/barks-restore/restore --title "{{title}}"

# Generate panel bounds for all restoreable pages in a volume or volumes
[group('comics')]
panels volume:
    {{uv_run}} barks-batch-panel-bounds --work-dir /mnt/2tb_drive/workdir/barks-restore/panel-bounds --volume {{volume}}

# Generate panel bounds for all restoreable pages in a title
[group('comics')]
panels-title title:
    {{uv_run}} barks-batch-panel-bounds --work-dir /mnt/2tb_drive/workdir/barks-restore/panel-bounds --title "{{title}}"

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
edit-volume-panel volume type page-panel:
    {{uv_run}} barks-edit-page --log-level WARNING --volume "{{volume}}" --type {{type}} --p-p {{page-panel}}

# Quickly edit a title panel from a volume page number
[group('utils')]
edit-title-panel title type page-panel:
    {{uv_run}} barks-edit-page --log-level WARNING --title "{{title}}" --type {{type}} --p-p {{page-panel}}

# Quickly edit a tile panel from a comic page number
[group('utils')]
edit-comic-panel title type comic-page-panel:
    {{uv_run}} barks-edit-page --log-level WARNING --title "{{title}}" --type {{type}} --cp-p {{comic-page-panel}}

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
               "{{barks_2tb_internal_books_dir}}/Carl Barks/Regression-Tests/Small/aaa-Chronological-dirs" \
               "{{barks_dir}}/The Comics/aaa-Chronological-dirs"

# Compare all build files to the last known good build files
[group('comics')]
compare-all:
    {{uv_run}} scripts/compare_build_root_dirs.py \
               "{{barks_2tb_internal_books_dir}}/Carl Barks/Regression-Tests/Big/aaa-Chronological-dirs" \
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

# Rsync all Barks files to the 2tb internal drive
[group('rsync')]
backup-to-2tb-internal:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_2tb_internal_backup_dir}}/"
    rsync --delete -avh "{{barks_reader_config_dir}}/"  "{{barks_2tb_internal_barks_reader_config_backup_dir}}/"

# Rsync all Barks files to the 2tb external drive
[group('rsync')]
[confirm]
backup-to-2tb-external:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_2tb_external_backup_dir}}/"
    rsync --delete -avh "{{barks_2tb_internal_books_dir}}/" "{{barks_2tb_external_books_dir}}/"
    rsync --delete -avh "{{barks_reader_config_dir}}/" "{{barks_2tb_external_barks_reader_config_backup_dir}}/"

# Rsync all Barks files FROM the 2tb external drive
[group('rsync')]
[confirm]
backup-from-2tb-external:
    rsync --delete -avh "{{barks_2tb_external_backup_dir}}/" "{{barks_dir}}/"
    rsync --delete -avh "{{barks_2tb_external_barks_reader_config_backup_dir}}/" "{{barks_reader_config_dir}}/"

# Rsync all Barks files to the 1tb external drive
[group('rsync')]
backup-to-1tb-external:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_1tb_external_backup_dir}}/"
    rsync --delete -avh "{{barks_2tb_internal_books_dir}}/" "{{barks_1tb_external_backup_big_dirs}}/"

# Rsync all Barks files to the 1tb external drive no. 2
[group('rsync')]
backup-to-1tb-external-2:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_1tb_external_backup_2_dir}}/"
    rsync --delete -avh "{{barks_2tb_internal_books_dir}}/" "{{barks_1tb_external_backup_2_big_dirs}}/"

# Rsync all Barks files to the 'music' external drive
[group('rsync')]
backup-to-music-external:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_music_external_backup_dir}}/"

# Rsync all Barks files to the 'restic' external drive
[group('rsync')]
backup-to-restic-external:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_restic_external_backup_dir}}/"

# Rsync all Barks files to the '750_Backup' external drive
[group('rsync')]
backup-to-750-backup-external:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_750_external_backup_dir}}/"
    rsync --delete -avh "{{barks_2tb_internal_books_dir}}/" "{{barks_750_external_backup_big_dirs}}/"
