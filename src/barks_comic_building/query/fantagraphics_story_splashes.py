"""List the splash pages of the stories in a Fantagraphics volume, by volume page.

What a splash is, is decided in one place: `barks_fantagraphics.splash_pages`, the rule
the reader's `scripts/find-splash-pages.py` tags stories with and its nightly check
holds the tags to. This tool used to have a rule of its own - five panels or fewer, of
unequal widths and heights - which could not see a page that is one panel, the plainest
splash there is, and never looked at page 1. So the two could name different pages of
one story.

The reader's script prints tag data for every story, numbered as the reader numbers
pages. This one answers for a volume or a title, with the pages numbered as the
volume's files are.
"""
# ruff: noqa: T201

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import typer
from barks_fantagraphics.barks_tags_data import SPLASH_EXCEPTIONS
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comic_book_info import (
    NON_COMIC_TITLES,
    is_covers_collection,
    is_one_pager_collection,
)
from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.fanta_comics_info import get_fanta_volume_str
from barks_fantagraphics.pages import get_sorted_srce_and_dest_pages
from barks_fantagraphics.splash_pages import get_panel_area_fractions, get_splash_pages
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg  # noqa: TC002

from barks_comic_building.cli_setup import get_comic_titles, init_logging

if TYPE_CHECKING:
    from barks_fantagraphics.comic_book import ComicBook

APP_LOGGING_NAME = "spla"


@dataclass(frozen=True, slots=True)
class StorySplashes:
    """The splash pages of one story, numbered as the volume's files are.

    Attributes:
        splashes: The story's splash pages.
        exempt: The pages the rule finds that `SPLASH_EXCEPTIONS` leaves out: page-1
            title panels judged by eye not to be splashes.
        not_panelled: The body pages with no panel-segments file, which cannot be judged.

    """

    splashes: list[str] = field(default_factory=list)
    exempt: list[str] = field(default_factory=list)
    not_panelled: list[str] = field(default_factory=list)


def has_story_pages(comic: ComicBook) -> bool:
    """Return whether a comic is a story, whose pages can be judged for splashes.

    Args:
        comic: The comic.

    Returns:
        False for an article and for the one-pager and cover collections, which the
        reader's splash tagging leaves out too.

    """
    title = comic.get_title_enum()

    return (
        title not in NON_COMIC_TITLES
        and not is_one_pager_collection(title)
        and not is_covers_collection(title)
    )


def get_story_splashes(comic: ComicBook) -> StorySplashes:
    """Return a story's splash pages, as the shared rule finds them.

    Only the page list is asked for, not the pages' files, so a story that is panelled
    but has a page still to restore is judged all the same.

    Args:
        comic: The story.

    Returns:
        The splash pages, the pages left out as exceptions, and the pages that have no
        panel-segments file to judge.

    """
    srce_and_dest_pages = get_sorted_srce_and_dest_pages(comic, get_full_paths=False)

    # Keyed by the volume's page, with the story's own page number kept alongside:
    # the exceptions are written in the story's page numbers, as the reader shows them.
    story_page_nums: dict[str, str] = {}
    panel_fractions: dict[str, list[float]] = {}
    not_panelled = []
    for srce_page, dest_page in zip(
        srce_and_dest_pages.srce_pages, srce_and_dest_pages.dest_pages, strict=True
    ):
        if srce_page.page_type is not PageType.BODY:
            continue

        srce_page_str = get_page_str(srce_page.page_num)

        panel_segments_file = comic.get_srce_panel_segments_file(srce_page_str)
        if not panel_segments_file.is_file():
            not_panelled.append(srce_page_str)
            continue

        segments = json.loads(panel_segments_file.read_text(encoding="utf-8"))
        panel_fractions[srce_page_str] = get_panel_area_fractions(segments)
        story_page_nums[srce_page_str] = str(dest_page.page_num)

    found = get_splash_pages(panel_fractions)

    title = comic.get_title_enum()
    if title not in SPLASH_EXCEPTIONS:
        return StorySplashes(found, [], not_panelled)

    # An entry with no pages leaves the whole title out.
    exempt_story_pages = SPLASH_EXCEPTIONS[title]
    exempt = [
        page
        for page in found
        if not exempt_story_pages or story_page_nums[page] in exempt_story_pages
    ]

    return StorySplashes([page for page in found if page not in exempt], exempt, not_panelled)


app = typer.Typer()


@app.command(help="Fantagraphics volumes splash pages")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    rows: dict[str, tuple[int, StorySplashes]] = {}
    for title in titles:
        comic_book = comics_database.get_comic_book(title)
        if not has_story_pages(comic_book):
            continue

        story_splashes = get_story_splashes(comic_book)
        if story_splashes.splashes or story_splashes.exempt or story_splashes.not_panelled:
            rows[comic_book.get_title_with_issue_num()] = (
                comic_book.get_fanta_volume(),
                story_splashes,
            )

    max_title_len = max((len(title) for title in rows), default=0)

    for title, (volume, story_splashes) in rows.items():
        if not story_splashes.splashes:
            continue
        splashes_str = ", ".join(story_splashes.splashes)
        print(
            f'"{title:<{max_title_len}}", {get_fanta_volume_str(volume)}, Splashes: {splashes_str}'
        )

    for heading, pages_of in (
        ("Left out by SPLASH_EXCEPTIONS", lambda story: story.exempt),
        ("Not judged, no panel segments", lambda story: story.not_panelled),
    ):
        noted = {title: pages_of(story) for title, (_volume, story) in rows.items()}
        if not any(noted.values()):
            continue
        print()
        print(f"{heading}:")
        for title, pages in noted.items():
            if pages:
                print(f'    "{title}": {", ".join(pages)}')


if __name__ == "__main__":
    app()
