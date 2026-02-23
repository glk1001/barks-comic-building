# ruff: noqa: T201
from pathlib import Path

import typer
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_title_from_volume_page
from comic_utils.common_typer_options import LogLevelArg
from intspan import intspan
from loguru_config import LoguruConfig

import barks_comic_building.log_setup as _log_setup

APP_LOGGING_NAME = "vttl"

_RESOURCES = Path(__file__).parent.parent / "resources"

app = typer.Typer()


@app.command(help="Find a title from a volume page number")
def main(
    volumes_str: str,
    page: str,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    _log_setup.log_level = log_level_str
    _log_setup.log_filename = "barks-cmds.log"
    _log_setup.APP_LOGGING_NAME = APP_LOGGING_NAME
    LoguruConfig.load(_RESOURCES / "log-config.yaml")

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
