import sys
import traceback
from pathlib import Path

import typer
from barks_fantagraphics.comic_book import ComicBook
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_titles
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comic_utils.timing import Timing
from intspan import intspan
from loguru import logger
from loguru_config import LoguruConfig

import barks_comic_building.log_setup as _log_setup
from barks_comic_building.build.additional_file_writing import write_summary_file
from barks_comic_building.build.build_comics import ComicBookBuilder

APP_LOGGING_NAME = "bbld"

_RESOURCES = Path(__file__).parent.parent / "resources"


def process_comic_book_titles(comics_database: ComicsDatabase, titles: list[str]) -> int:
    assert len(titles) > 0

    ret_code = 0

    for title in titles:
        comic = comics_database.get_comic_book(title)
        ret = process_comic_book(comic)
        if ret != 0:
            ret_code = ret

    return ret_code


def process_comic_book(comic: ComicBook) -> int:
    process_timing = Timing()

    # noinspection PyBroadException
    try:
        comic_book_builder = ComicBookBuilder(comic)

        comic_book_builder.build()

        mark_process_end(process_timing)

        write_summary_file(
            comic,
            comic_book_builder.get_srce_dim(),
            comic_book_builder.get_required_dim(),
            comic_book_builder.get_srce_and_dest_pages(),
            comic_book_builder.get_max_dest_page_timestamp(),
            process_timing,
        )
    except AssertionError:
        _, _, tb = sys.exc_info()
        tb_info = traceback.extract_tb(tb)
        filename, line, _func, text = tb_info[-1]
        msg = f'Assert failed at "{filename}:{line}" for statement "{text}".'
        logger.exception(msg)
        return 1
    except Exception:  # noqa: BLE001
        logger.exception("Build error: ")
        return 1

    return 0


def mark_process_end(process_timing: Timing) -> None:
    logger.info(
        f"Time taken to complete comic: {process_timing.get_elapsed_time_in_seconds()} seconds",
    )


app = typer.Typer()


@app.command(help="Create a clean Barks comic from Fantagraphics source")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    _log_setup.log_level = log_level_str
    _log_setup.log_filename = "build-comics.log"
    _log_setup.APP_LOGGING_NAME = APP_LOGGING_NAME
    LoguruConfig.load(_RESOURCES / "log-config.yaml")

    if volumes_str and title_str:
        msg = "Options --volume and --title are mutually exclusive."
        raise typer.BadParameter(msg)

    volumes = list(intspan(volumes_str))
    comics_database = ComicsDatabase()

    exit_code = process_comic_book_titles(
        comics_database, get_titles(comics_database, volumes, title_str)
    )

    if exit_code != 0:
        print(f"\nThere were errors: exit code = {exit_code}.")  # noqa: T201
        sys.exit(exit_code)


if __name__ == "__main__":
    app()
