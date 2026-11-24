# ruff: noqa: T201

import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Annotated

import typer
from comic_utils.common_typer_options import LogLevelArg
from loguru import logger

from barks_comic_building.cli_setup import init_logging
from barks_comic_building.restore.restore_pipeline import RestorePipeline, check_for_errors

APP_LOGGING_NAME = "srst"

SCALE = 4

app = typer.Typer()


@app.command(help="Make single restored file")
def main(  # noqa: PLR0913
    srce_file: Path,
    srce_upscale_file: Path,
    dest_restored_file: Path,
    dest_upscayled_restored_file: Path,
    dest_svg_restored_file: Path,
    work_dir: Annotated[
        Path | None,
        typer.Option(
            help="Where the intermediates go, and stay. By default a directory of this"
            " run's own is made for them and removed once the page has been restored."
        ),
    ] = None,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "single-restore-pipeline.log", log_level_str)

    out_dir = dest_restored_file.parent
    if not out_dir.is_dir():
        print(f'ERROR: Can\'t find output directory: "{out_dir}".')
        sys.exit(1)

    # A directory of this run's own unless one is asked for. It used to be a fixed
    # "/tmp/working", where the work files are named by page stem alone - so two runs for
    # the same page number of different volumes wrote over each other's intermediates,
    # and every run left its 150MB behind.
    made_work_dir = work_dir is None
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="barks-single-restore-"))
    else:
        work_dir.mkdir(parents=True, exist_ok=True)

    start_restore = time.time()

    restore_process = RestorePipeline(
        work_dir,
        srce_file,
        srce_upscale_file,
        SCALE,
        dest_restored_file,
        dest_upscayled_restored_file,
        dest_svg_restored_file,
    )
    restore_process.do_part1()
    restore_process.do_part2_memory_hungry()
    restore_process.do_part3()
    restore_process.do_part4_memory_hungry()

    logger.info(f"\nTime taken to restore the page: {int(time.time() - start_restore)}s.")

    check_for_errors([restore_process])

    if restore_process.errors_occurred:
        # Kept, since they are what there is to go on.
        logger.error(f'The work files have been left in "{work_dir}".')
        sys.exit(1)

    if made_work_dir:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    app()
