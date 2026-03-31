# ruff: noqa: T201


import typer
from barks_fantagraphics.comic_book import get_total_num_pages
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_titles
from comic_utils.common_typer_options import LogLevelArg, VolumesArg
from intspan import intspan

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "scnt"

app = typer.Typer()


@app.command(help="Fantagraphics volumes story page counts")
def main(
    volumes_str: VolumesArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    volumes = list(intspan(volumes_str))
    comics_database = ComicsDatabase()

    titles = get_titles(comics_database, volumes, title="")

    page_count = 0
    for title in titles:
        comic_book = comics_database.get_comic_book(title)
        num_pages = get_total_num_pages(comic_book)
        if num_pages <= 1:
            msg = f'For title "{title}", the page count is too small.'
            raise ValueError(msg)
        page_count += num_pages

    print(f"{len(titles)} titles, {page_count} pages")


if __name__ == "__main__":
    app()
