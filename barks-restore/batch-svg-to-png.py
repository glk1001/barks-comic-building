import concurrent.futures
import os
import sys
import time
from pathlib import Path

from barks_fantagraphics.barks_titles import is_non_comic_title
from barks_fantagraphics.comics_cmd_args import CmdArgNames, CmdArgs
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_utils import get_abbrev_path
from loguru import logger
from loguru_config import LoguruConfig
from src.image_io import svg_file_to_png

SCALE = 4


def svgs_to_pngs(title_list: list[str]) -> None:
    start = time.time()

    num_png_files = 0
    for title in title_list:
        if is_non_comic_title(title):
            logger.info(f'Not a comic title - not converting "{title}".')
            continue

        logger.info(f'Converting svg to png for "{title}"...')

        comic = comics_database.get_comic_book(title)

        srce_files = comic.get_srce_restored_svg_story_files(RESTORABLE_PAGE_TYPES)

        with concurrent.futures.ProcessPoolExecutor() as executor:
            for srce_file in srce_files:
                executor.submit(convert_svg_to_png, srce_file)

        num_png_files += len(srce_files)

    logger.info(f"\nTime taken to convert all {num_png_files} files: {int(time.time() - start)}s.")


def convert_svg_to_png(srce_svg: str) -> None:
    try:
        if not os.path.isfile(srce_svg):
            raise FileNotFoundError(f'Could not find srce file: "{srce_svg}".')

        png_file = srce_svg + ".png"
        if os.path.isfile(png_file):
            logger.warning(f'Dest png file exists - skipping: "{get_abbrev_path(png_file)}".')
            return

        logger.info(
            f'Converting svg file "{get_abbrev_path(srce_svg)}"'
            f' to dest png "{get_abbrev_path(png_file)}".',
        )
        svg_file_to_png(srce_svg, png_file)

    except Exception:
        logger.exception("Error: ")
        return


if __name__ == "__main__":
    # TODO(glk): Some issue with type checking inspection?
    # noinspection PyTypeChecker
    cmd_args = CmdArgs("Convert titles from svg to png", CmdArgNames.TITLE | CmdArgNames.VOLUME)
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variables accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    log_filename = "batch-svg-to-png.log"
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = cmd_args.get_comics_database()

    svgs_to_pngs(cmd_args.get_titles())
