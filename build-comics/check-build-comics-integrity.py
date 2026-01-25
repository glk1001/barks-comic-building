import sys
from pathlib import Path

import typer
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_titles
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comics_integrity import ComicsIntegrityChecker
from intspan import intspan
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "cbld"

app = typer.Typer()
log_level = ""
log_filename = "check-build-comics-integrity.log"


@app.command(help="Check the integrity of all previously built comics")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    no_check_for_unexpected_files: bool = False,
    no_check_symlinks: bool = False,
) -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    if volumes_str and title_str:
        msg = "Options --volume and --title are mutually exclusive."
        raise typer.BadParameter(msg)

    volumes = list(intspan(volumes_str))
    comics_database = ComicsDatabase()

    integrity_checker = ComicsIntegrityChecker(
        comics_database, no_check_for_unexpected_files, no_check_symlinks
    )
    exit_code = integrity_checker.check_comics_integrity(
        get_titles(comics_database, volumes, title_str)
    )

    if exit_code != 0:
        print(f"\nThere were errors: exit code = {exit_code}.")  # noqa: T201
        sys.exit(exit_code)


if __name__ == "__main__":
    app()
