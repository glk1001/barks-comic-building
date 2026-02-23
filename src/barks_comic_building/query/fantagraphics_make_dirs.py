from pathlib import Path

import typer
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg
from loguru_config import LoguruConfig

import barks_comic_building.log_setup as _log_setup

APP_LOGGING_NAME = "mdir"

_RESOURCES = Path(__file__).parent.parent / "resources"

app = typer.Typer()


@app.command(help="Make all required Fantagraphics directories")
def main(log_level_str: LogLevelArg = "DEBUG") -> None:
    _log_setup.log_level = log_level_str
    _log_setup.log_filename = "barks-cmds.log"
    _log_setup.APP_LOGGING_NAME = APP_LOGGING_NAME
    LoguruConfig.load(_RESOURCES / "log-config.yaml")

    comics_database = ComicsDatabase()

    comics_database.make_all_fantagraphics_directories()


if __name__ == "__main__":
    app()
