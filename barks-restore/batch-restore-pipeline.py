import concurrent.futures
import time
from pathlib import Path

import psutil
import typer
from barks_fantagraphics.barks_titles import is_non_comic_title
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_titles
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comic_utils.pil_image_utils import copy_file_to_png
from intspan import intspan
from loguru import logger
from loguru_config import LoguruConfig
from src.restore_pipeline import RestorePipeline, check_for_errors

APP_LOGGING_NAME = "bres"

SCALE = 4
SMALL_RAM = 16 * 1024 * 1024 * 1024


def restore(comics_database: ComicsDatabase, title_list: list[str], work_dir: Path) -> None:
    start = time.time()

    num_restored = 0
    for title in title_list:
        if is_non_comic_title(title):
            num_restored += copy_title(comics_database, title)
        else:
            num_restored += restore_title(comics_database, title, work_dir)

    if num_restored > 0:
        logger.info(
            f'\nTime taken to restore all {len(title_list)} titles": {int(time.time() - start)}s.',
        )


def copy_title(comics_database: ComicsDatabase, title_str: str) -> int:
    logger.info(f'Copying non-comic title "{title_str}".')

    comic = comics_database.get_comic_book(title_str)
    srce_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    dest_restored_files = comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)

    for srce_file, dest_file in zip(srce_files, dest_restored_files, strict=True):
        if Path(dest_file).is_file():
            logger.warning(
                f'Dest file exists - skipping: "{get_abbrev_path(dest_file)}".',
            )
            continue

        logger.info(
            f'Copying "{get_abbrev_path(srce_file[0])}" to "{get_abbrev_path(dest_file)}".',
        )
        copy_file_to_png(srce_file[0], dest_file)

    return len(srce_files)


def restore_title(comics_database: ComicsDatabase, title: str, work_dir: Path) -> int:
    start = time.time()

    logger.info(f'Processing story "{title}".')

    comic = comics_database.get_comic_book(title)

    title_work_dir = work_dir / title
    title_work_dir.mkdir(parents=True, exist_ok=True)

    srce_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    srce_upscayl_files = comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)
    dest_restored_files = comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)
    dest_restored_upscayled_files = comic.get_srce_restored_upscayled_story_files(
        RESTORABLE_PAGE_TYPES,
    )
    dest_restored_svg_files = comic.get_srce_restored_svg_story_files(RESTORABLE_PAGE_TYPES)

    restore_processes: list[RestorePipeline] = []

    for (
        srce_file,
        srce_upscayl_file,
        dest_restored_file,
        dest_upscayled_restored_file,
        dest_svg_restored_file,
    ) in zip(
        srce_files,
        srce_upscayl_files,
        dest_restored_files,
        dest_restored_upscayled_files,
        dest_restored_svg_files,
        strict=True,
    ):
        if not srce_upscayl_file[0].is_file():
            logger.error(f'Could not find srce upscayl file - skipping: "{srce_upscayl_file[0]}".')
            continue
        if dest_restored_file.is_file():
            logger.warning(
                f'Dest file exists - skipping: "{get_abbrev_path(dest_restored_file)}".',
            )
            continue

        logger.info(
            f'Restoring srce files "{get_abbrev_path(srce_file[0])}",'
            f' "{get_abbrev_path(srce_upscayl_file[0])}"'
            f' to dest "{get_abbrev_path(dest_restored_file)}".',
        )

        restore_processes.append(
            RestorePipeline(
                title_work_dir,
                Path(srce_file[0]),
                Path(srce_upscayl_file[0]),
                SCALE,
                Path(dest_restored_file),
                Path(dest_upscayled_restored_file),
                Path(dest_svg_restored_file),
            ),
        )

    if len(restore_processes) == 0:
        logger.info(f'No pages to restore for title "{title}".')
        return 0

    run_restore(restore_processes)

    logger.info(
        f"\nTime taken to restore all {len(restore_processes)}"
        f" title files: {int(time.time() - start)}s.",
    )

    check_for_errors(restore_processes)

    return len(restore_processes)


part1_max_workers = None


def run_restore_part1(proc: RestorePipeline) -> None:
    logger.info(f'Starting restore part 1 for "{proc.srce_upscale_file.name}".')
    proc.do_part1()


part2_max_workers = 1 if psutil.virtual_memory().total < SMALL_RAM else 6


def run_restore_part2(proc: RestorePipeline) -> None:
    logger.info(f'Starting restore part 2 for "{proc.srce_upscale_file.name}".')
    proc.do_part2_memory_hungry()


part3_max_workers = None


def run_restore_part3(proc: RestorePipeline) -> None:
    logger.info(f'Starting restore part 3 for "{proc.srce_upscale_file.name}".')
    proc.do_part3()


part4_max_workers = 1 if psutil.virtual_memory().total < SMALL_RAM else 5


def run_restore_part4(proc: RestorePipeline) -> None:
    logger.info(f'Starting restore part 4 for "{proc.srce_upscale_file.name}".')
    proc.do_part4_memory_hungry()


def run_restore(restore_processes: list[RestorePipeline]) -> None:
    logger.info(f"Starting restore for {len(restore_processes)} processes.")

    with concurrent.futures.ProcessPoolExecutor(part1_max_workers) as executor:
        for process in restore_processes:
            executor.submit(run_restore_part1, process)

    with concurrent.futures.ProcessPoolExecutor(part2_max_workers) as executor:
        for process in restore_processes:
            executor.submit(run_restore_part2, process)

    with concurrent.futures.ProcessPoolExecutor(part3_max_workers) as executor:
        for process in restore_processes:
            executor.submit(run_restore_part3, process)

    with concurrent.futures.ProcessPoolExecutor(part4_max_workers) as executor:
        for process in restore_processes:
            executor.submit(run_restore_part4, process)


app = typer.Typer()
log_level = ""
log_filename = "batch-restore.log"


@app.command(help="Make restored files")
def main(
    work_dir: Path = typer.Option(...),  # noqa: B008
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    if volumes_str and title_str:
        msg = "Options --volume and --title are mutually exclusive."
        raise typer.BadParameter(msg)

    volumes = list(intspan(volumes_str))
    comics_database = ComicsDatabase()

    work_dir.mkdir(parents=True, exist_ok=True)

    restore(comics_database, get_titles(comics_database, volumes, title_str), work_dir)


if __name__ == "__main__":
    app()
