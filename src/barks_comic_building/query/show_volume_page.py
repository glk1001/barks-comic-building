"""Open the image viewer on the restored file of a Fantagraphics volume's page."""
# ruff: noqa: T201

import sys
from pathlib import Path

import typer
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg, PagesArg, VolumesArg

from barks_comic_building.cli_setup import get_page_num, get_single_volume, init_logging
from barks_comic_building.query.image_viewer import open_viewer
from barks_comic_building.query.page_files import get_volume_page_file

APP_LOGGING_NAME = "svpg"

app = typer.Typer()


@app.command(help="Open image viewer for Fanta volume page")
def main(
    volumes_str: VolumesArg = "",
    page_num_str: PagesArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    volume = get_single_volume(volumes_str)
    page_num = get_page_num("--page", page_num_str)
    comics_database = ComicsDatabase()

    restored_srce_file = get_volume_page_file(
        volume,
        page_num,
        lambda vol: Path(comics_database.get_fantagraphics_restored_volume_image_dir(vol)),
        ".png",
    )
    if not restored_srce_file.is_file():
        print(f'Error: Could not find restored file "{restored_srce_file}".')
        sys.exit(1)

    print(f"{volume}: {page_num:03d}")

    open_viewer(restored_srce_file)


if __name__ == "__main__":
    app()
