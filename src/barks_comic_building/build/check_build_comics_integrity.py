import sys

import typer
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg

from barks_comic_building.build.comics_integrity import ComicsIntegrityChecker
from barks_comic_building.cli_setup import get_comic_titles, init_logging

APP_LOGGING_NAME = "cbld"

app = typer.Typer()


@app.command(help="Check the integrity of all previously built comics")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    no_check_for_unexpected_files: bool = False,
    no_check_symlinks: bool = False,
) -> None:
    init_logging(APP_LOGGING_NAME, "check-build-comics-integrity.log", log_level_str)

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    integrity_checker = ComicsIntegrityChecker(
        comics_database, no_check_for_unexpected_files, no_check_symlinks
    )
    exit_code = integrity_checker.check_comics_integrity(titles)

    if exit_code != 0:
        print(f"\nThere were errors: exit code = {exit_code}.")  # noqa: T201
        sys.exit(exit_code)


if __name__ == "__main__":
    app()
