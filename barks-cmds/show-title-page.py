# ruff: noqa: T201

import subprocess
import sys
from pathlib import Path

import typer
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg, PagesArg, TitleArg
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "sttl"

VIEWER_EXE = ["/usr/bin/loupe"]

app = typer.Typer()
log_level = ""


def open_viewer(image_file: Path) -> None:
    command = [*VIEWER_EXE, str(image_file)]

    _proc = subprocess.Popen(command)  # noqa: S603

    print(f'Image Viewer should now be showing image "{image_file}".')


@app.command(help="Open image viewer for comic page")
def main(
    title: TitleArg,
    page_num_str: PagesArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = ComicsDatabase()

    comic = comics_database.get_comic_book(title)
    volume = comic.get_fanta_volume()
    valid_page_list = [
        p.page_filenames for p in comic.page_images_in_order if p.page_type == PageType.BODY
    ]

    first_page = int(valid_page_list[0])
    page = first_page if not page_num_str else first_page + int(page_num_str) - 1
    page = get_page_str(page)

    if page not in valid_page_list:
        print(f'Page {page_num_str} not valid for "{title}".')
        sys.exit(1)

    restored_dir = Path(comics_database.get_fantagraphics_restored_volume_image_dir(volume))
    restored_srce_file = restored_dir / (page + ".png")
    if not restored_srce_file.is_file():
        print(f'Error: Could not find restored file "{restored_srce_file}".')
        sys.exit(1)

    print(f'"{title}" [{volume}]: {first_page}')

    open_viewer(restored_srce_file)


if __name__ == "__main__":
    app()
