"""Write an empty ini file for each story of a volume that has none yet.

A story's first and last pages come from the volume's table of contents, when there is
one in the internal data directory; otherwise they are left as zero to fill in by hand.
"""

import itertools
import json
from typing import Any

import typer
from barks_fantagraphics.comic_book_info import COVERS_SET, ONE_PAGERS
from barks_fantagraphics.comics_consts import INTERNAL_DATA_DIR
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_issue_titles, get_titles_and_info
from barks_fantagraphics.comics_utils import get_abbrev_path
from barks_fantagraphics.fanta_comics_info import get_fanta_volume_str
from comic_utils.common_typer_options import LogLevelArg, VolumesArg
from loguru import logger

from barks_comic_building.cli_setup import get_single_volume, init_logging

APP_LOGGING_NAME = "mcfg"

TOC_PAGE_OFFSET = 7
TOC_DIR = INTERNAL_DATA_DIR
# The entry that closes a table of contents. It is no story: it is there to give the
# last story a next entry, and so a last page.
TOC_END_TITLE = "END"


def get_toc_page_ranges(toc_info: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Return each story's first and last volume page from a table of contents.

    A story ends on the page before the next entry starts, so the last story needs an
    entry after it: the `TOC_END_TITLE` entry. Without one the last story was silently
    left out, and looking it up raised a bare `KeyError`.

    Args:
        toc_info: The table of contents as read from its json file: entries with a
            "title" and the "page" it starts on, among entries of other kinds.

    Returns:
        The page range of each story by title; empty for an empty table of contents.

    Raises:
        ValueError: If the table of contents has entries and does not end in
            `TOC_END_TITLE`.

    """
    toc_entries = [entry for entry in toc_info if "title" in entry]
    if not toc_entries:
        return {}

    if toc_entries[-1]["title"] != TOC_END_TITLE:
        msg = (
            f'The table of contents must end in an "{TOC_END_TITLE}" entry,'
            f' not "{toc_entries[-1]["title"]}": without one its last story has no last page.'
        )
        raise ValueError(msg)

    return {
        entry["title"]: (
            entry["page"] + TOC_PAGE_OFFSET,
            next_entry["page"] + TOC_PAGE_OFFSET - 1,
        )
        for entry, next_entry in itertools.pairwise(toc_entries)
    }


def create_empty_config_file(  # noqa: PLR0913
    comics_database: ComicsDatabase,
    volume: int,
    ttl: str,
    is_barks_ttl: bool,
    first_page: int,
    last_page: int,
) -> None:
    """Write a story's ini file with nothing in it but its volume and its body pages.

    Args:
        comics_database: The database that says where the story's ini file goes.
        volume: The story's Fantagraphics volume.
        ttl: The story's title.
        is_barks_ttl: Whether the title is Barks's own; if not the ini's is left blank.
        first_page: The story's first volume page.
        last_page: The story's last volume page.

    Raises:
        FileExistsError: If the story already has an ini file.

    """
    ini_file = comics_database.get_ini_file(ttl)
    if ini_file.exists():
        msg = f'Ini file "{ini_file}" already exists.'
        raise FileExistsError(msg)

    logger.info(f'Creating empty config file: "{get_abbrev_path(ini_file)}".')
    with ini_file.open("w") as f:
        f.write("[info]\n")
        if is_barks_ttl:
            f.write(f"title = {ttl}\n")
        else:
            f.write("title =\n")
        f.write(f"source_comic = {get_fanta_volume_str(volume)}\n")
        f.write("\n")
        f.write("[pages]\n")
        f.write("title_empty = TITLE\n")
        f.write(f"{first_page} - {last_page} = BODY\n")


app = typer.Typer()


@app.command(help="Make empty comic configs")
def main(
    volumes_str: VolumesArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    volume = get_single_volume(volumes_str)
    comics_database = ComicsDatabase()

    toc_file = TOC_DIR / f"vol-{volume}-toc-gemini.json"
    toc_info = [] if not toc_file.is_file() else json.loads(toc_file.read_bytes())
    try:
        toc_dict = get_toc_page_ranges(toc_info)
    except ValueError as e:
        msg = f'"{toc_file}": {e}'
        raise typer.BadParameter(msg) from e

    titles_and_info = get_titles_and_info(
        comics_database, [volume], title="", configured_only=False
    )
    titles_config_info = get_issue_titles(comics_database, titles_and_info)

    if len(titles_config_info) == 0:
        logger.error(f"There are no titles to configure for Fanta volume {volume}.")
    else:
        titles = []
        not_in_toc = []
        for title_config_info in titles_config_info:
            title = title_config_info[0]
            comic_book_info = title_config_info[2].comic_book_info
            is_barks_title = comic_book_info.is_barks_title
            title_is_configured = title_config_info[3]

            # Covers get no ini file. They are pre-baked into the synthetic "All
            # Covers" collection from COVER_LOCATIONS rather than built from a
            # per-title config, and they are not TOC entries either, so the lookup
            # below would not find them.
            if comic_book_info.title in COVERS_SET:
                logger.info(f'Title: "{title}" is a cover - skipping.')
                continue

            # One-pagers get no ini file either, for the same reason: they are
            # pre-baked into "All One-Pagers" from ONE_PAGER_LOCATIONS, and nothing
            # reads a per-one-pager config - the reader opens a one-pager as a page
            # of that collection (see navigation_coordinator.read_comic). Writing
            # one here would only produce a file that never gets used.
            if comic_book_info.title in ONE_PAGERS:
                logger.info(f'Title: "{title}" is a one-pager - skipping.')
                continue

            if title_is_configured:
                logger.info(f'Title: "{title}" is already configured - skipping.')
                continue

            if toc_dict and title not in toc_dict:
                # Usually a title the table of contents spells another way.
                not_in_toc.append(title)
                continue

            start_page, end_page = toc_dict.get(title, (0, 0))

            titles.append((title, is_barks_title, start_page, end_page))

        if not_in_toc:
            # Before anything is written: half a volume's ini files is worse than none.
            msg = (
                f'These titles are not in the table of contents "{toc_file}":'
                f" {', '.join(f'"{title}"' for title in not_in_toc)}."
            )
            raise typer.BadParameter(msg)

        logger.info("")
        for title, is_barks_title, start_page, end_page in titles:
            create_empty_config_file(
                comics_database, volume, title, is_barks_title, start_page, end_page
            )
