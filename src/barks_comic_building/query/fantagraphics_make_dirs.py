import typer
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "mdir"

app = typer.Typer()


@app.command(help="Make all required Fantagraphics directories")
def main(log_level_str: LogLevelArg = "DEBUG") -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    comics_database = ComicsDatabase()

    comics_database.make_all_fantagraphics_directories()


if __name__ == "__main__":
    app()
