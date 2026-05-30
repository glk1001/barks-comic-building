# ruff: noqa: T201

import subprocess
import sys
from pathlib import Path

import typer
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_volume_and_page
from comic_utils.common_typer_options import LogLevelArg, PagesArg, TitleArg

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "sttl"

VIEWER_EXE = ["/usr/bin/loupe"]


def open_viewer(image_file: Path) -> None:
    command = [*VIEWER_EXE, str(image_file)]

    _proc = subprocess.Popen(command)  # noqa: S603

    print(f'Image Viewer should now be showing image "{image_file}".')


app = typer.Typer()


@app.command(help="Open image viewer for comic page")
def main(
    title: TitleArg,
    page_num_str: PagesArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    comics_database = ComicsDatabase()

    volume, page = get_volume_and_page(comics_database, title, page_num_str)

    restored_dir = Path(comics_database.get_fantagraphics_restored_volume_image_dir(volume))
    restored_srce_file = restored_dir / (page + ".png")
    if not restored_srce_file.is_file():
        print(f'Error: Could not find restored file "{restored_srce_file}".')
        sys.exit(1)

    print(f'"{title}" [{volume}]: {page}')

    open_viewer(restored_srce_file)


if __name__ == "__main__":
    app()
