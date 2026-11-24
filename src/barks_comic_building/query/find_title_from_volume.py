"""Say which title a page of a Fantagraphics volume belongs to."""
# ruff: noqa: T201

import typer
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_title_from_volume_page
from comic_utils.common_typer_options import LogLevelArg

from barks_comic_building.cli_setup import get_page_num, get_single_volume, init_logging

APP_LOGGING_NAME = "fvol"  # cspell:disable-line

app = typer.Typer()


@app.command(help="Find a title from a volume page number")
def main(
    volumes_str: str,
    page: str,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    volume = get_single_volume(volumes_str)
    page = get_page_str(get_page_num("PAGE", page))
    comics_database = ComicsDatabase()

    found_title, found_page = get_title_from_volume_page(comics_database, volume, page)

    if found_title:
        print(f'For volume {volume}, page {page}, found title "{found_title}", page {found_page}.')
    else:
        print(f"Could not find title for volume {volume}, page {page}.")


if __name__ == "__main__":
    app()
