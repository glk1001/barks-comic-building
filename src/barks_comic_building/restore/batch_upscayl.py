import time
from pathlib import Path

import typer
from barks_fantagraphics.barks_titles import is_non_comic_title
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_titles
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from intspan import intspan
from loguru import logger
from loguru_config import LoguruConfig

import barks_comic_building.log_setup as _log_setup
from barks_comic_building.restore.upscale_image import upscale_image_file

APP_LOGGING_NAME = "bups"

_RESOURCES = Path(__file__).parent.parent / "resources"

SCALE = 4


def upscayl(comics_database: ComicsDatabase, title_list: list[str]) -> None:
    start = time.time()

    num_upscayled_files = 0
    for title in title_list:
        if is_non_comic_title(title):
            logger.info(f'Not a comic title - not upscayling "{title}".')
            continue

        logger.info(f'Upscayling story "{title}"...')
        comic = comics_database.get_comic_book(title)

        srce_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
        upscayl_files = comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)

        for srce_file, (dest_file, _is_mod_file) in zip(srce_files, upscayl_files, strict=True):
            if upscayl_file(srce_file[0], dest_file):
                num_upscayled_files += 1

    logger.info(
        f"\nTime taken to upscayl all {num_upscayled_files} files: {int(time.time() - start)}s.",
    )


def upscayl_file(srce_file: Path, dest_file: Path) -> bool:
    if not srce_file.is_file():
        msg = f'Could not find srce file: "{srce_file}".'
        raise FileNotFoundError(msg)
    if dest_file.is_file():
        logger.warning(f'Dest upscayl file exists - skipping: "{get_abbrev_path(dest_file)}".')
        return False

    start = time.time()

    logger.info(
        f'Upscayling srce file "{get_abbrev_path(srce_file)}"'
        f' to dest upscayl file "{get_abbrev_path(dest_file)}".',
    )
    upscale_image_file(srce_file, dest_file, SCALE)

    logger.info(f"\nTime taken to upscayl file: {int(time.time() - start)}s.")

    return True


app = typer.Typer()


@app.command(help="Make upscayled files")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    _log_setup.log_level = log_level_str
    _log_setup.log_filename = "batch-upscayl.log"
    _log_setup.APP_LOGGING_NAME = APP_LOGGING_NAME
    LoguruConfig.load(_RESOURCES / "log-config.yaml")

    if volumes_str and title_str:
        msg = "Options --volume and --title are mutually exclusive."
        raise typer.BadParameter(msg)

    volumes = list(intspan(volumes_str))
    comics_database = ComicsDatabase()

    upscayl(comics_database, get_titles(comics_database, volumes, title_str))


if __name__ == "__main__":
    app()
