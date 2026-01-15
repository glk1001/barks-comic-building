# ruff: noqa: T201
from pathlib import Path

import typer
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_title_from_volume_page
from comic_utils.common_typer_options import LogLevelArg
from intspan import intspan
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "vttl"

app = typer.Typer()
log_level = ""


@app.command(help="Find a title from a volume page number")
def main(
    volumes_str: str,
    page: str,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    volumes = list(intspan(volumes_str))
    assert len(volumes) == 1
    page = get_page_str(int(page))
    comics_database = ComicsDatabase()

    found_title, found_page = get_title_from_volume_page(comics_database, volumes[0], page)

    if found_title:
        print(
            f"For volume {volumes_str}, page {page},"
            f' found title "{found_title}", page {found_page}"'
        )
    else:
        print(f"Could not find title for volume {volumes_str}, page {page}.")


if __name__ == "__main__":
    app()
