# ruff: noqa: T201

from pathlib import Path

import typer
from barks_fantagraphics.comic_book import get_total_num_pages
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_titles
from comic_utils.common_typer_options import LogLevelArg, VolumesArg
from intspan import intspan
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "scnt"

app = typer.Typer()
log_level = ""


@app.command(help="Fantagraphics volumes story page counts")
def main(
    volumes_str: VolumesArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

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
