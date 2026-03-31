import concurrent.futures
import time
from pathlib import Path

import typer
from barks_fantagraphics.barks_titles import is_non_comic_title
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from loguru import logger

from barks_comic_building.cli_setup import get_comic_titles, init_logging
from barks_comic_building.restore.image_io import svg_file_to_png

APP_LOGGING_NAME = "bsvg"

SCALE = 4


def svgs_to_pngs(comics_database: ComicsDatabase, title_list: list[str]) -> None:
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


def convert_svg_to_png(srce_svg: Path) -> None:
    # noinspection PyBroadException
    try:
        if not srce_svg.is_file():
            msg = f'Could not find srce file: "{srce_svg}".'
            raise FileNotFoundError(msg)  # noqa: TRY301

        png_file = Path(str(srce_svg) + ".png")
        if png_file.is_file():
            logger.warning(f'Dest png file exists - skipping: "{get_abbrev_path(png_file)}".')
            return

        logger.info(
            f'Converting svg file "{get_abbrev_path(srce_svg)}"'
            f' to dest png "{get_abbrev_path(png_file)}".',
        )
        svg_file_to_png(srce_svg, png_file)

    except Exception:  # noqa: BLE001
        logger.exception("Error: ")
        return


app = typer.Typer()


@app.command(help="Create png files from svg files")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "batch-svg-to-png.log", log_level_str)

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    svgs_to_pngs(comics_database, titles)


if __name__ == "__main__":
    app()
