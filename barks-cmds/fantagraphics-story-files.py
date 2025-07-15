import logging
import os
import sys
from pathlib import Path
from typing import List

from barks_fantagraphics.comic_book import ModifiedType
from barks_fantagraphics.comics_cmd_args import CmdArgs, CmdArgNames, ExtraArg
from barks_fantagraphics.comics_logging import setup_logging
from barks_fantagraphics.comics_utils import (
    get_abbrev_path,
    get_timestamp,
    get_timestamp_as_str,
)
from barks_fantagraphics.pages import (
    get_sorted_srce_and_dest_pages,
    get_restored_srce_dependencies,
)


def print_sources(indent: int, source_list: List[str]) -> None:
    if not source_list:
        print()
        return

    print(f'"{source_list[0]}"')
    for srce in source_list[1:]:
        print(" " * indent + f'"{srce}"')


def get_filepath_with_date(file: str, timestamp: float, out_of_date_marker: str) -> str:
    missing_timestamp = "FILE MISSING          "  # same length as timestamp str

    if os.path.isfile(file):
        file_str = get_abbrev_path(file)
        file_timestamp = get_timestamp_as_str(timestamp, "-", date_time_sep=" ", hr_sep=":")
    else:
        file_str = file
        file_timestamp = missing_timestamp

    return f'{file_timestamp}:{out_of_date_marker}"{file_str}"'


MODS_ARG = "--mods"

extra_args: List[ExtraArg] = [ExtraArg(MODS_ARG, action="store_true", type=None, default=False)]

# TODO(glk): Some issue with type checking inspection?
# noinspection PyTypeChecker
cmd_args = CmdArgs("Fantagraphics source files", CmdArgNames.TITLE | CmdArgNames.VOLUME, extra_args)
args_ok, error_msg = cmd_args.args_are_valid()
if not args_ok:
    logging.error(error_msg)
    sys.exit(1)

setup_logging(cmd_args.get_log_level())

comics_database = cmd_args.get_comics_database()
mods_only = cmd_args.get_extra_arg(MODS_ARG)

titles = cmd_args.get_titles()

for title in titles:
    comic_book = comics_database.get_comic_book(title)

    srce_and_dest_pages = get_sorted_srce_and_dest_pages(comic_book, get_full_paths=True)

    srce_pages = srce_and_dest_pages.srce_pages
    dest_pages = srce_and_dest_pages.dest_pages

    max_len_page_type = max([len(dp.page_type.name) for dp in dest_pages])

    print()
    print(f'"{title}" source files:')

    for srce_page, dest_page in zip(srce_pages, dest_pages):
        dest_page_num = Path(dest_page.page_filename).stem
        srce_page_num = Path(srce_page.page_filename).stem
        page_type_str = dest_page.page_type.name
        prev_timestamp = get_timestamp(dest_page.page_filename)

        sources = [get_filepath_with_date(dest_page.page_filename, prev_timestamp, " ")]
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
                dependency.file, dependency.timestamp, out_of_date_str
            )
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
