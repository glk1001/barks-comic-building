import concurrent.futures
import sys
import time
from pathlib import Path

import psutil
from barks_fantagraphics.barks_titles import is_non_comic_title
from barks_fantagraphics.comics_cmd_args import CmdArgNames, CmdArgs
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.pil_image_utils import copy_file_to_png
from loguru import logger
from loguru_config import LoguruConfig
from src.restore_pipeline import RestorePipeline, check_for_errors

APP_LOGGING_NAME = "bres"

SCALE = 4
SMALL_RAM = 16 * 1024 * 1024 * 1024


def restore(title_list: list[str]) -> None:
    start = time.time()

    for title in title_list:
        if is_non_comic_title(title):
            copy_title(title)
        else:
            restore_title(title)

    logger.info(
        f'\nTime taken to restore all {len(title_list)} titles": {int(time.time() - start)}s.',
    )


def copy_title(title_str: str) -> None:
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


def restore_title(title: str) -> None:
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

    run_restore(restore_processes)

    logger.info(
        f"\nTime taken to restore all {len(restore_processes)}"
        f" title files: {int(time.time() - start)}s.",
    )

    check_for_errors(restore_processes)


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


if __name__ == "__main__":
    # TODO(glk): Some issue with type checking inspection?
    # noinspection PyTypeChecker
    cmd_args = CmdArgs(
        "Restore titles", CmdArgNames.TITLE | CmdArgNames.VOLUME | CmdArgNames.WORK_DIR
    )
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variables accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    log_filename = "batch-restore.log"
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    work_dir = cmd_args.get_work_dir()
    work_dir.mkdir(parents=True, exist_ok=True)

    comics_database = cmd_args.get_comics_database()

    restore(cmd_args.get_titles())
