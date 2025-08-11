set dotenv-load

barks_dir := "$HOME/Books/Carl Barks"
barks_2tb_internal_backup_dir := "/mnt/2tb_drive/barks-backup/Carl Barks"
barks_2tb_external_backup_dir := "/media/greg/2tb_drive_backup/barks-backup/Carl Barks"
barks_2tb_internal_books_dir := "/mnt/2tb_drive/Books"
barks_2tb_external_books_dir := "/media/greg/2tb_drive_backup/Books"
barks_1tb_external_backup_dir := "/media/greg/1TB_Backup/barks-backup/Carl Barks"
barks_1tb_external_backup_big_dirs := "/media/greg/1TB_Backup/barks-backup/Carl Barks-big-dirs"
barks_music_external_backup_dir := "/media/greg/MusicBarksBackup/Books/Carl Barks"
barks_restic_external_backup_dir := "/media/greg/restic_backup/Books/Carl Barks"


_default:
    just --list --unsorted | tee /tmp/junk.log

show-env:
    env


# Get Fanta volume page and status info
[group('comics')]
info volume:
    uv run barks-cmds/fantagraphics-info.py --log-level WARN --volume {{volume}}

# Build a title
[group('comics')]
build title:
    uv run build-comics/batch-build-comics.py build --log-level INFO --title "{{title}}"

# Check the integrity of a volume or volumes
[group('comics')]
check volume:
    uv run build-comics/batch-build-comics.py check-integrity --log-level WARN --volume {{volume}}

# Upscayl all restoreable pages in a volume or volumes
[group('comics')]
upscayl volume:
    uv run barks-restore/batch-upscayl.py --volume {{ volume }}

# Restore all restoreable pages in a volume or volumes
[group('comics')]
restore volume:
    uv run barks-restore/batch-restore-pipeline.py --work-dir /mnt/2tb_drive/workdir/barks-restore/restore --volume {{volume}}

# Generate panel bounds for all restoreable pages in a volume or volumes
[group('comics')]
panels volume:
    uv run barks-restore/batch-panel-bounds.py --work-dir /mnt/2tb_drive/workdir/barks-restore/panel-bounds --volume {{volume}}

# Make empty config files for all restoreable pages in a volume or volumes
[group('comics')]
make-empty-configs volume:
    uv run barks-cmds/make-empty-configs.py --log-level INFO --volume {{ volume }}

# Show any differences between Fanta original pages and added pages for a volume or volumes
[group('comics')]
show-diffs volume:
    uv run barks-cmds/show-fixes-diffs.py --log-level INFO --volume {{ volume }}

# Do a small build test
[group('comics')]
test-small:
    bash small-build-test.sh
    bash compare-build-dirs.sh "{{barks_2tb_external_books_dir}}/Carl Barks/Regression-Tests/Small/aaa-Chronological-dirs"\
                               "{{barks_dir}}/The Comics/aaa-Chronological-dirs"

# Compare all build files to the last known good build files
[group('comics')]
compare-all:
    bash compare-build-dirs.sh "{{barks_2tb_external_books_dir}}/Carl Barks/Regression-Tests/Big/aaa-Chronological-dirs"\
                               "{{barks_dir}}/The Comics/aaa-Chronological-dirs"

# Do a big image compare of restored to original looking for upscayl errors
[group('comics')]
check-for-upscayl-errors:
    bash compare-fanta-image-dirs.sh "{{barks_dir}}/Fantagraphics-restored" "{{barks_dir}}/Fantagraphics-original" 50% 10000

# Do a big image compare of restored to original looking for obvious changes
[group('comics')]
compare-restored-orig:
    bash compare-fanta-image-dirs.sh "{{barks_dir}}/Fantagraphics-restored" "{{barks_dir}}/Fantagraphics-original" 50% 5000

# Rsync all Barks files to the 2tb internal drive
[group('rsync')]
backup-to-2tb-internal:
    rsync --delete -avh "{{barks_dir}}/"  "{{barks_2tb_internal_backup_dir}}/"

# Rsync all Barks files to the 2tb external drive
[group('rsync')]
[confirm]
backup-to-2tb-external:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_2tb_external_backup_dir}}/"
    rsync --delete -avh "{{barks_2tb_internal_books_dir}}/" "{{barks_2tb_external_books_dir}}/"

# Rsync all Barks files FROM the 2tb external drive
[group('rsync')]
[confirm]
backup-from-2tb-external:
    rsync --delete -avh "{{barks_2tb_external_backup_dir}}/"  "{{barks_dir}}/"

# Rsync all Barks files to the 1tb external drive
[group('rsync')]
backup-to-1tb-external:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_1tb_external_backup_dir}}/"
    rsync --delete -avh "{{barks_2tb_internal_books_dir}}/" "{{barks_1tb_external_backup_big_dirs}}/"

# Rsync all Barks files to the 'music' external drive
[group('rsync')]
backup-to-music-external:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_music_external_backup_dir}}/"

# Rsync all Barks files to the 'restic' external drive
[group('rsync')]
backup-to-restic-external:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_restic_external_backup_dir}}/"
