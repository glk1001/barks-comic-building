"""List the files each built page of a title was made from, with their dates."""
# ruff: noqa: T201

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer
from barks_fantagraphics.comic_book import ModifiedType, get_page_str
from barks_fantagraphics.comic_book_info import NON_COMIC_TITLES
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_utils import (
    get_abbrev_path,
    get_timestamp,
    get_timestamp_as_str,
)
from barks_fantagraphics.fanta_comics_info import HAND_RESTORED_TITLES
from barks_fantagraphics.pages import (
    SrceDependency,
    get_restored_srce_dependencies,
    get_sorted_srce_and_dest_pages,
)
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg  # noqa: TC002

from barks_comic_building.build.utils import walk_srce_dependency_chain
from barks_comic_building.cli_setup import get_comic_titles, init_logging
from barks_comic_building.query.build_state import get_unrestored_page_dependencies

if TYPE_CHECKING:
    import zipfile
    from collections.abc import Sequence

    from barks_fantagraphics.comic_book import ComicBook
    from barks_fantagraphics.page_classes import CleanPage

APP_LOGGING_NAME = "sfil"

OUT_OF_DATE_MARKER = "*"
NOT_ON_DISK = -1.0


def print_sources(indent: int, source_list: list[str]) -> None:
    if not source_list:
        print()
        return

    print(f'"{source_list[0]}"')
    for srce in source_list[1:]:
        print(" " * indent + f'"{srce}"')


def get_filepath_with_date(
    is_a_comic: bool, file: Path | zipfile.Path, timestamp: float, out_of_date_marker: str
) -> str:
    if not is_a_comic and (("upscayled" in str(file)) or ("svg" in str(file))):
        return ""

    missing_timestamp = "FILE MISSING          "  # same length as timestamp str

    if file.is_file():
        file_str = get_abbrev_path(file)
        file_timestamp = get_timestamp_as_str(timestamp, "-", date_time_sep=" ", hr_sep=":")
    else:
        file_str = file
        file_timestamp = missing_timestamp

    return f'{file_timestamp}:{out_of_date_marker}"{file_str}"'


def get_out_of_date_files(
    dependencies: Sequence[SrceDependency],
    dest_file: Path,
    dest_timestamp: float,
    ini_file: Path,
    *,
    is_a_comic: bool,
) -> set[Path | zipfile.Path]:
    """Return the files of a page's listing to mark as newer than what was made from them.

    The chain is graded by `walk_srce_dependency_chain`, the walk `barks-check-build`
    uses, so the listing and the integrity report cannot disagree about a page. This tool
    used to walk the list itself, comparing every row with the row above it, and that
    marked files that were in order: the row after a missing stage, which was compared
    with the missing stage's -1, and the title page's inset, which was compared with
    the ini file's checkout time.

    A file the page depends on but was not made from in sequence - the intro inset, a
    hand-drawn panel bounds fix - is compared with the built page instead. The ini file
    is never marked: it is git-tracked, so its time dates a checkout and not an edit.

    Args:
        dependencies: The page's dependencies, as the pipeline reports them.
        dest_file: The built page.
        dest_timestamp: The built page's timestamp, or `NOT_ON_DISK`.
        ini_file: The comic's ini file.
        is_a_comic: False for the non-comic titles, whose pages have no restore chain.

    Returns:
        The dependencies to mark: a stage newer than the stage or page made from it, a
        stage that is missing, and an independent file newer than the built page.

    """
    staleness = walk_srce_dependency_chain(
        dependencies, dest_file, dest_timestamp, None, is_a_comic=is_a_comic
    )
    out_of_date: set[Path | zipfile.Path] = {newer for newer, _older in staleness.stale_pairs}

    if dest_timestamp >= 0:
        out_of_date.update(
            dependency.file
            for dependency in dependencies
            if dependency.independent
            and dependency.file != ini_file
            and dependency.timestamp > dest_timestamp
        )

    return out_of_date


def get_missing_srce_file(comic: ComicBook, srce_page: CleanPage) -> Path:
    """Return the file the build would make a page from, for a page that has none.

    Args:
        comic: The comic the page is in.
        srce_page: A page `ComicBook.get_final_srce_story_file` finds no file for.

    Returns:
        The restored page of a page that is restored by the pipeline, and otherwise the
        page's scan or the fix that stands in for it.

    """
    page_num_str = get_page_str(srce_page.page_num)

    if (
        comic.get_title_str() not in HAND_RESTORED_TITLES
        and srce_page.page_type in RESTORABLE_PAGE_TYPES
    ):
        return comic.get_srce_restored_image_dir() / f"{page_num_str}.png"

    return comic.get_final_srce_original_story_file(page_num_str, srce_page.page_type)[0]


def get_listed_dependencies(comic: ComicBook, srce_page: CleanPage) -> list[SrceDependency]:
    """Return the files to list under a page, whether or not the page can be built yet.

    `get_restored_srce_dependencies` raises on a page with no file to build from, which
    stopped the whole listing at the first page of a title that is part-way through
    restoring - the state in which the listing is most wanted. Such a page is listed
    with that file as missing, above the stages that are there to make it from.

    Args:
        comic: The comic the page is in.
        srce_page: The page.

    Returns:
        The page's dependencies, in the order they are listed.

    """
    try:
        return get_restored_srce_dependencies(comic, srce_page)
    except FileNotFoundError:
        return [
            SrceDependency(get_missing_srce_file(comic, srce_page), NOT_ON_DISK, independent=False),
            *get_unrestored_page_dependencies(comic, srce_page),
        ]


def print_story_files(comic_book: ComicBook, *, mods: bool) -> None:
    """Print each page of a comic with the files it is made from and their dates.

    Only the page list is asked for, not the pages' files: resolving the files raises on
    the first page that has none.

    Args:
        comic_book: The comic to list.
        mods: Whether to list only the pages that are made from a fixes file.

    """
    srce_and_dest_pages = get_sorted_srce_and_dest_pages(comic_book, get_full_paths=False)

    srce_pages = srce_and_dest_pages.srce_pages
    dest_pages = srce_and_dest_pages.dest_pages

    max_len_page_type = max([len(dp.page_type.name) for dp in dest_pages])
    is_a_comic_book = comic_book.get_title_enum() not in NON_COMIC_TITLES

    print()
    print(f'"{comic_book.get_title_str()}" source files:')

    for srce_page, dest_page in zip(srce_pages, dest_pages, strict=True):
        dest_page_num = Path(dest_page.page_filename).stem
        page_type_str = dest_page.page_type.name
        # A title that is restored but not built yet has no dest pages to stat.
        dest_file = comic_book.get_dest_image_dir() / dest_page.page_filename
        dest_timestamp = get_timestamp(dest_file) if dest_file.is_file() else NOT_ON_DISK

        dependencies = get_listed_dependencies(comic_book, srce_page)
        out_of_date = get_out_of_date_files(
            dependencies,
            dest_file,
            dest_timestamp,
            comic_book.ini_file,
            is_a_comic=is_a_comic_book,
        )

        sources = [get_filepath_with_date(is_a_comic_book, dest_file, dest_timestamp, " ")]
        is_modded = False
        for dependency in dependencies:
            if dependency.mod_type != ModifiedType.ORIGINAL:
                is_modded = True
            file_info = get_filepath_with_date(
                is_a_comic_book,
                dependency.file,
                dependency.timestamp,
                OUT_OF_DATE_MARKER if dependency.file in out_of_date else " ",
            )
            if file_info:
                sources.append(file_info)

        if not mods or is_modded:
            print(
                f"    {dest_page_num}"
                f" ({dest_page.page_num:02}) - {page_type_str:{max_len_page_type}}: ",
                end="",
            )
            print_sources(4 + 2 + 5 + 2 + 3 + max_len_page_type + 2, sources)

    print()


app = typer.Typer()


@app.command(help="Fantagraphics source files")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    mods: bool = False,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    for title in titles:
        print_story_files(comics_database.get_comic_book(title), mods=mods)


if __name__ == "__main__":
    app()
