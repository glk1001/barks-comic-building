# ruff: noqa: T201

import os
import sys
from pathlib import Path

from barks_fantagraphics import panel_bounding
from barks_fantagraphics.barks_titles import NON_COMIC_TITLES
from barks_fantagraphics.comic_book import ModifiedType
from barks_fantagraphics.comics_cmd_args import CmdArgNames, CmdArgs, ExtraArg
from barks_fantagraphics.comics_utils import (
    get_abbrev_path,
    get_timestamp,
    get_timestamp_as_str,
)
from barks_fantagraphics.pages import get_restored_srce_dependencies, get_sorted_srce_and_dest_pages
from loguru import logger
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "sfil"


def print_sources(indent: int, source_list: list[str]) -> None:
    if not source_list:
        print()
        return

    print(f'"{source_list[0]}"')
    for srce in source_list[1:]:
        print(" " * indent + f'"{srce}"')


def get_filepath_with_date(
    is_a_comic: bool, file: str, timestamp: float, out_of_date_marker: str
) -> str:
    if not is_a_comic and (("upscayled" in file) or ("svg" in file)):
        return ""

    missing_timestamp = "FILE MISSING          "  # same length as timestamp str

    if os.path.isfile(file):
        file_str = get_abbrev_path(file)
        file_timestamp = get_timestamp_as_str(timestamp, "-", date_time_sep=" ", hr_sep=":")
    else:
        file_str = file
        file_timestamp = missing_timestamp

    return f'{file_timestamp}:{out_of_date_marker}"{file_str}"'


MODS_ARG = "--mods"
EXTRA_ARGS: list[ExtraArg] = [ExtraArg(MODS_ARG, action="store_true", type=None, default=False)]

if __name__ == "__main__":
    # TODO(glk): Some issue with type checking inspection?
    # noinspection PyTypeChecker
    cmd_args = CmdArgs(
        "Fantagraphics source files", CmdArgNames.TITLE | CmdArgNames.VOLUME, EXTRA_ARGS
    )
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variable accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    panel_bounding.warn_on_panels_bbox_height_less_than_av = False
    comics_database = cmd_args.get_comics_database()
    mods_only = cmd_args.get_extra_arg(MODS_ARG)

    titles = cmd_args.get_titles()

    for title in titles:
        comic_book = comics_database.get_comic_book(title)

        srce_and_dest_pages = get_sorted_srce_and_dest_pages(comic_book, get_full_paths=True)

        srce_pages = srce_and_dest_pages.srce_pages
        dest_pages = srce_and_dest_pages.dest_pages

        max_len_page_type = max([len(dp.page_type.name) for dp in dest_pages])
        is_a_comic_book = comic_book.get_title_enum() not in NON_COMIC_TITLES

        print()
        print(f'"{title}" source files:')

        for srce_page, dest_page in zip(srce_pages, dest_pages):
            dest_page_num = Path(dest_page.page_filename).stem
            srce_page_num = Path(srce_page.page_filename).stem
            page_type_str = dest_page.page_type.name
            prev_timestamp = get_timestamp(dest_page.page_filename)

            sources = [
                get_filepath_with_date(
                    is_a_comic_book, dest_page.page_filename, prev_timestamp, " "
                )
            ]
            is_modded = False
            for dependency in get_restored_srce_dependencies(comic_book, srce_page):
                if dependency.mod_type != ModifiedType.ORIGINAL:
                    is_modded = True
                out_of_date_str = (
                    "*"
                    if (dependency.timestamp < 0) or (dependency.timestamp > prev_timestamp)
                    else " "
                )
                file_info = get_filepath_with_date(
                    is_a_comic_book, dependency.file, dependency.timestamp, out_of_date_str
                )
                if file_info:
                    sources.append(file_info)
                    prev_timestamp = dependency.timestamp

            if not mods_only or is_modded:
                print(
                    f"    {dest_page_num}"
                    f" ({dest_page.page_num:02}) - {page_type_str:{max_len_page_type}}: ",
                    end="",
                )
                print_sources(4 + 2 + 5 + 2 + 3 + max_len_page_type + 2, sources)

        print()
