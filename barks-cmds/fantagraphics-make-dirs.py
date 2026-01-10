from pathlib import Path

import typer
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "mdir"

app = typer.Typer()
log_level = ""


@app.command(help="Make all required Fantagraphics directories")
def main(log_level_str: LogLevelArg = "DEBUG") -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = ComicsDatabase()

    comics_database.make_all_fantagraphics_directories()


if __name__ == "__main__":
    app()
