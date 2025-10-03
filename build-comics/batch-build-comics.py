import argparse
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

from additional_file_writing import write_summary_file
from barks_fantagraphics.comic_book import ComicBook
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_utils import get_titles_sorted_by_submission_date
from build_comics import ComicBookBuilder
from comic_utils.timing import Timing
from comics_integrity import ComicsIntegrityChecker
from intspan import intspan
from loguru import logger
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "bbld"


def process_comic_book_titles(
    comics_db: ComicsDatabase,
    titles: list[str],
) -> int:
    assert len(titles) > 0

    ret_code = 0

    for title in titles:
        comic = comics_db.get_comic_book(title)
        ret = process_comic_book(comic)
        if ret != 0:
            ret_code = ret

    return ret_code


def process_comic_book(comic: ComicBook) -> int:
    process_timing = Timing(datetime.now(UTC))

    # noinspection PyBroadException
    try:
        comic_book_builder = ComicBookBuilder(comic)

        comic_book_builder.build()

        process_timing.end_time = datetime.now(UTC)
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
        # raise Exception
        logger.exception("Build error: ")
        return 1

    return 0


def mark_process_end(process_timing: Timing) -> None:
    logger.info(
        f"Time taken to complete comic: {process_timing.get_elapsed_time_in_seconds()} seconds",
    )


LOG_LEVEL_ARG = "--log-level"
VOLUME_ARG = "--volume"
TITLE_ARG = "--title"
NO_CHECK_FOR_UNEXPECTED_FILES_ARG = "--no-check-for-unexpected-files"
NO_CHECK_SYMLINKS_ARG = "--no-check-symlinks"

BUILD_ARG = "build"
CHECK_INTEGRITY_ARG = "check-integrity"


def get_args() -> argparse.Namespace:
    global_parser = argparse.ArgumentParser(
        description="Create a clean Barks comic from Fantagraphics source.",
    )

    subparsers = global_parser.add_subparsers(
        dest="cmd_name",
        title="subcommands",
        help="comic building commands",
        required=True,
    )

    build_comics_parser = subparsers.add_parser(BUILD_ARG, help="build comics")
    build_comics_parser.add_argument(VOLUME_ARG, action="store", type=str, required=False)
    build_comics_parser.add_argument(TITLE_ARG, action="store", type=str, required=False)
    build_comics_parser.add_argument(
        LOG_LEVEL_ARG,
        action="store",
        type=str,
        required=False,
        default="INFO",
    )

    check_integrity_parser = subparsers.add_parser(
        CHECK_INTEGRITY_ARG,
        help="check the integrity of all previously built comics",
    )
    check_integrity_parser.add_argument(
        NO_CHECK_FOR_UNEXPECTED_FILES_ARG,
        action="store_true",
        default=False,
    )
    check_integrity_parser.add_argument(
        NO_CHECK_SYMLINKS_ARG,
        action="store_true",
        default=False,
    )
    check_integrity_parser.add_argument(VOLUME_ARG, action="store", type=str, required=False)
    check_integrity_parser.add_argument(TITLE_ARG, action="store", type=str, required=False)
    check_integrity_parser.add_argument(
        LOG_LEVEL_ARG,
        action="store",
        type=str,
        required=False,
        default="INFO",
    )

    args = global_parser.parse_args()

    if args.cmd_name == CHECK_INTEGRITY_ARG and args.title and args.volume:
        msg = f"Cannot have both '{TITLE_ARG} and '{VOLUME_ARG}'."
        raise ValueError(msg)
    if args.cmd_name == BUILD_ARG and args.title and args.volume:
        msg = f"Cannot have both '{TITLE_ARG} and '{VOLUME_ARG}'."
        raise ValueError(msg)

    return args


def get_titles(args: argparse.Namespace) -> list[str]:
    assert args.cmd_name in (CHECK_INTEGRITY_ARG, BUILD_ARG)

    if args.title:
        return [args.title]

    if args.volume is not None:
        vol_list = list(intspan(args.volume))
        titles_and_info = comics_database.get_configured_titles_in_fantagraphics_volumes(vol_list)
        return get_titles_sorted_by_submission_date(titles_and_info)

    return []


if __name__ == "__main__":
    cmd_args = get_args()

    # Global variable accessed by loguru-config.
    log_level = cmd_args.log_level
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = ComicsDatabase()

    if cmd_args.cmd_name == CHECK_INTEGRITY_ARG:
        integrity_checker = ComicsIntegrityChecker(
            comics_database, cmd_args.no_check_for_unexpected_files, cmd_args.no_check_symlinks
        )
        exit_code = integrity_checker.check_comics_integrity(get_titles(cmd_args))
    elif cmd_args.cmd_name == BUILD_ARG:
        exit_code = process_comic_book_titles(comics_database, get_titles(cmd_args))
    else:
        err_msg = f'ERROR: Unknown cmd_arg "{cmd_args.cmd_name}".'
        raise ValueError(err_msg)

    if exit_code != 0:
        print(f"\nThere were errors: exit code = {exit_code}.")  # noqa: T201
        sys.exit(exit_code)
