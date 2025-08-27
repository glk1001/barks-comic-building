barks_dir := "$HOME/Books/Carl Barks"

barks_2tb_internal_backup_dir := "/mnt/2tb_drive/barks-backup/Carl Barks"
barks_2tb_external_backup_dir := "/media/greg/2tb_drive_backup/barks-backup/Carl Barks"
barks_2tb_internal_books_dir := "/mnt/2tb_drive/Books"
barks_2tb_external_books_dir := "/media/greg/2tb_drive_backup/Books"
barks_1tb_external_backup_dir := "/media/greg/1TB_Backup/barks-backup/Carl Barks"
barks_1tb_external_backup_big_dirs := "/media/greg/1TB_Backup/barks-backup/Carl Barks-big-dirs"
barks_music_external_backup_dir := "/media/greg/MusicBarksBackup/Books/Carl Barks"
barks_restic_external_backup_dir := "/media/greg/restic_backup/Books/Carl Barks"

barks_reader_config_dir := "$HOME/.config/barks-reader"
barks_2tb_internal_barks_reader_config_backup_dir := "/mnt/2tb_drive/barks-reader"
barks_2tb_external_barks_reader_config_backup_dir := "/media/greg/2tb_drive_backup/barks-reader"

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
    uv run "{{ source_dir() }}/barks-cmds/fantagraphics-info.py" --log-level WARNING --volume {{volume}}

# Get title page counts for Fanta volume or volumes
[group('comics')]
page-count volume:
    uv run "{{ source_dir() }}/barks-cmds/fantagraphics-stories-page-count.py" --log-level WARNING --volume {{volume}}

# Build a title
[group('comics')]
build-title title:
    uv run "{{ source_dir() }}/build-comics/batch-build-comics.py" build --log-level INFO --title "{{title}}"

# Build a volume or volumes
[group('comics')]
build volume:
    uv run "{{ source_dir() }}/build-comics/batch-build-comics.py" build --log-level INFO --volume "{{volume}}"

# Check the integrity of a volume or volumes
[group('comics')]
check volume:
    uv run "{{ source_dir() }}/build-comics/batch-build-comics.py" check-integrity --log-level WARNING --volume {{volume}}

# Upscayl all restoreable pages in a volume or volumes
[group('comics')]
upscayl volume:
    uv run "{{ source_dir() }}/barks-restore/batch-upscayl.py" --volume {{ volume }}

# Upscayl all restoreable pages in a title
[group('comics')]
upscayl-title title:
    uv run "{{ source_dir() }}/barks-restore/batch-upscayl.py" --title "{{title}}"

# Restore all restoreable pages in a volume or volumes
[group('comics')]
restore volume:
    uv run "{{ source_dir() }}/barks-restore/batch-restore-pipeline.py" \
           --work-dir /mnt/2tb_drive/workdir/barks-restore/restore --volume {{volume}}

# Restore all restoreable pages in a title
[group('comics')]
restore-title title:
    uv run "{{ source_dir() }}/barks-restore/batch-restore-pipeline.py" \
           --work-dir /mnt/2tb_drive/workdir/barks-restore/restore --title "{{title}}"

# Generate panel bounds for all restoreable pages in a volume or volumes
[group('comics')]
panels volume:
    uv run "{{ source_dir() }}/barks-restore/batch-panel-bounds.py" \
           --work-dir /mnt/2tb_drive/workdir/barks-restore/panel-bounds --volume {{volume}}

# Generate panel bounds for all restoreable pages in a title
[group('comics')]
panels-title title:
    uv run "{{ source_dir() }}/barks-restore/batch-panel-bounds.py" \
           --work-dir /mnt/2tb_drive/workdir/barks-restore/panel-bounds --title "{{title}}"

# Make empty config files for all restoreable pages in a volume or volumes
[group('comics')]
make-empty-configs volume:
    uv run "{{ source_dir() }}/barks-cmds/make-empty-configs.py" --log-level INFO --volume {{ volume }}

# Show any differences between Fanta original pages and added pages for a volume or volumes
[group('comics')]
show-diffs volume:
    uv run "{{ source_dir() }}/barks-cmds/show-fixes-diffs.py" --log-level INFO --volume {{ volume }}

# Do a small build test
[group('comics')]
test-small:
    bash scripts/small-build-test.sh
    uv run scripts/compare_build_root_dirs.py \
         "{{barks_2tb_internal_books_dir}}/Carl Barks/Regression-Tests/Small/aaa-Chronological-dirs" \
         "{{barks_dir}}/The Comics/aaa-Chronological-dirs"

# Compare all build files to the last known good build files
[group('comics')]
compare-all:
    uv run scripts/compare_build_root_dirs.py \
         "{{barks_2tb_internal_books_dir}}/Carl Barks/Regression-Tests/Big/aaa-Chronological-dirs" \
         "{{barks_dir}}/The Comics/aaa-Chronological-dirs"

# Do a big image compare of restored to original looking for upscayl errors
[group('comics')]
check-for-upscayl-errors volume:
    uv run scripts/compare_fanta_image_dirs.py "{{barks_dir}}/Fantagraphics-restored" \
                                               "{{barks_dir}}/Fantagraphics-original" 50% 10000 {{volume}}

# Do a big image compare of restored to original looking for obvious changes
[group('comics')]
compare-restored-orig volume:
    uv run scripts/compare_fanta_image_dirs.py "{{barks_dir}}/Fantagraphics-restored" \
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

# Rsync all Barks files to the 'music' external drive
[group('rsync')]
backup-to-music-external:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_music_external_backup_dir}}/"

# Rsync all Barks files to the 'restic' external drive
[group('rsync')]
backup-to-restic-external:
    rsync --delete -avh "{{barks_dir}}/" "{{barks_restic_external_backup_dir}}/"
