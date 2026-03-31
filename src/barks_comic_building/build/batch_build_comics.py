import sys

import typer
from barks_fantagraphics.comic_book import ComicBook
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comic_utils.timing import Timing
from loguru import logger

from barks_comic_building.build.additional_file_writing import write_summary_file
from barks_comic_building.build.build_comics import ComicBookBuilder
from barks_comic_building.cli_setup import get_comic_titles, init_logging

APP_LOGGING_NAME = "bbld"


def process_comic_book_titles(comics_database: ComicsDatabase, titles: list[str]) -> int:
    assert len(titles) > 0

    ret_code = 0

    for title in titles:
        comic = comics_database.get_comic_book(title)
        ret = process_comic_book(comic)
        if ret != 0:
            ret_code = ret_code or ret

    return ret_code


def process_comic_book(comic: ComicBook) -> int:
    process_timing = Timing()

    try:
        comic_book_builder = ComicBookBuilder(comic)

        comic_book_builder.build()

        logger.info(
            f"Time taken to complete comic: {process_timing.get_elapsed_time_in_seconds()} seconds",
        )

        write_summary_file(
            comic,
            comic_book_builder.get_srce_dim(),
            comic_book_builder.get_required_dim(),
            comic_book_builder.get_srce_and_dest_pages(),
            comic_book_builder.get_max_dest_page_timestamp(),
            process_timing,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Build error:")
        return 1

    return 0


app = typer.Typer()


@app.command(help="Create a clean Barks comic from Fantagraphics source")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "build-comics.log", log_level_str)

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    exit_code = process_comic_book_titles(comics_database, titles)

    if exit_code != 0:
        print(f"\nThere were errors: exit code = {exit_code}.")  # noqa: T201
        sys.exit(exit_code)


if __name__ == "__main__":
    app()
