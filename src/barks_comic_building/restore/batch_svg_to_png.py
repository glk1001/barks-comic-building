import concurrent.futures
import sys
import time
from collections import Counter
from enum import StrEnum
from pathlib import Path

import typer
from barks_fantagraphics.comic_book_info import is_non_comic_title
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comic_utils.pil_image_utils import get_image_size
from loguru import logger

from barks_comic_building.cli_setup import get_comic_titles, init_logging
from barks_comic_building.restore.image_io import svg_file_to_optimized_png
from barks_comic_building.restore.page_state import get_ink_mask_file

APP_LOGGING_NAME = "bsvg"

MAX_WORKERS = 4


class SvgToPngOutcome(StrEnum):
    """What happened to one page's ink mask."""

    CONVERTED = "converted"
    SKIPPED = "skipped"  # The mask was already there.
    FAILED = "failed"


def svgs_to_pngs(comics_database: ComicsDatabase, title_list: list[str]) -> int:
    """Make the ink mask png for every traced page of each title that lacks one.

    Args:
        comics_database: The comics database.
        title_list: The titles to convert.

    Returns:
        How many pages could not be converted.

    """
    start = time.time()

    outcomes: Counter[SvgToPngOutcome] = Counter()
    for title in title_list:
        if is_non_comic_title(title):
            logger.info(f'Not a comic title - not converting "{title}".')
            continue

        logger.info(f'Converting svg to png for "{title}"...')

        comic = comics_database.get_comic_book(title)

        srce_files = [f[0] for f in comic.get_final_srce_story_files(RESTORABLE_PAGE_TYPES)]
        srce_svg_files = comic.get_srce_restored_svg_story_files(RESTORABLE_PAGE_TYPES)

        with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [
                executor.submit(convert_svg_to_png, srce_file, srce_svg_file)
                for srce_file, srce_svg_file in zip(srce_files, srce_svg_files, strict=True)
            ]

            # Read back rather than left to finish unseen. The count used to be the number
            # of pages submitted, so a run in which every page was skipped, or every page
            # failed, reported having converted them all.
            outcomes.update(future.result() for future in futures)

    num_failed = outcomes[SvgToPngOutcome.FAILED]
    summary = (
        f"converted {outcomes[SvgToPngOutcome.CONVERTED]},"
        f" skipped {outcomes[SvgToPngOutcome.SKIPPED]} already there,"
        f" failed {num_failed}"
    )
    logger.info(
        f"\nTime taken for {outcomes.total()} file(s) - {summary}: {int(time.time() - start)}s."
    )

    return num_failed


def convert_svg_to_png(srce_file: Path, srce_svg: Path) -> SvgToPngOutcome:
    """Make one page's ink mask from its traced line art, at the size of its source page.

    Runs in a worker process, so a failure is logged here and reported in the return
    value rather than raised.

    Args:
        srce_file: The page the mask has to match the size of.
        srce_svg: The traced line art.

    Returns:
        What happened.

    """
    # noinspection PyBroadException
    try:
        if not srce_file.is_file():
            msg = f'Could not find srce file: "{srce_file}".'
            raise FileNotFoundError(msg)  # noqa: TRY301
        if not srce_svg.is_file():
            msg = f'Could not find srce svg file: "{srce_svg}".'
            raise FileNotFoundError(msg)  # noqa: TRY301

        png_file = get_ink_mask_file(srce_svg)
        if png_file.is_file():
            logger.warning(f'Dest png file exists - skipping: "{get_abbrev_path(png_file)}".')
            return SvgToPngOutcome.SKIPPED

        srce_width, srce_height = get_image_size(srce_file)

        logger.info(
            f'Converting svg file "{get_abbrev_path(srce_svg)}"'
            f' to dest png {srce_width} x {srce_height} "{get_abbrev_path(png_file)}".',
        )
        svg_file_to_optimized_png(srce_svg, srce_width, srce_height, png_file)

    except Exception:  # noqa: BLE001
        logger.exception(f'Could not convert "{srce_svg}": ')
        return SvgToPngOutcome.FAILED

    return SvgToPngOutcome.CONVERTED


app = typer.Typer()


@app.command(help="Create png files from svg files")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "batch-svg-to-png.log", log_level_str)

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    if svgs_to_pngs(comics_database, titles):
        sys.exit(1)


if __name__ == "__main__":
    app()
