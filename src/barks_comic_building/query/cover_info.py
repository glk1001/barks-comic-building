"""Report the configured state of the Barks covers.

Covers are `PageType.COVER`: they are built full-page and are never restored or
cropped to panel bounds, so a cover's only per-title state is whether its CCBDL
reprint location has been authored in `COVER_LOCATIONS` - `X` (missing) or `C`
(configured). Every cover is listed, located or not.

At the bottom the report says whether the synthetic "All Covers" collection -
which is assembled from the located covers by `barks-stage-covers` and then built
like any other title - is currently built.
"""

from dataclasses import dataclass
from pathlib import Path

import typer
from barks_fantagraphics.barks_covers import (
    BARKS_COVERS,
    BarksCover,
    get_cover_location,
    get_cover_title,
)
from barks_fantagraphics.barks_titles import ENUM_TO_STR_TITLE, Titles
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comic_issues import SHORT_ISSUE_NAME
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.comic_consts import MONTH_AS_SHORT_STR
from comic_utils.common_typer_options import LogLevelArg, VolumesArg
from intspan import intspan
from rich.text import Text

from barks_comic_building.build.collection_staging import original_scan_slot
from barks_comic_building.build.stage_covers import get_staged_links_by_title
from barks_comic_building.cli_setup import init_logging
from barks_comic_building.query.build_state import (
    CONFIGURED_FLAG,
    NOT_CONFIGURED_FLAG,
    PROBLEM_STYLE,
    get_staged_link_stem,
    get_state_filter,
)
from barks_comic_building.query.collection_report import (
    filter_rows,
    get_report_table,
    print_collection_report,
)

APP_LOGGING_NAME = "icvr"

COLLECTION_TITLE = ENUM_TO_STR_TITLE[Titles.ALL_COVERS]

# A cover is either located in the CCBDL volumes or it is not - there is no further
# per-cover work, because a COVER page is never restored or panel-bounded.
COVER_STATE_FLAGS = [
    NOT_CONFIGURED_FLAG,
    CONFIGURED_FLAG,
]

DONE_FLAG = CONFIGURED_FLAG

# Problem codes. Only what is actionable: a cover having no upscayled png and no
# inset file are both true of every cover and are by design (a COVER page is built
# full-page from the original scan, and the reader's title panel falls back to its
# emergency inset), so neither is reported.
LINK_PROBLEM = "link"  # the FANTA_02 original-scan .jpg is not staged
DATE_PROBLEM = "date"  # incomplete submitted date, which submitted-order sorts on


@dataclass
class CoverRow:
    """What the cover report shows for one cover.

    Attributes:
        display_title: The cover's title as shown.
        issue_title: The issue the cover is from.
        kind: The kind of cover.
        volume: The Fantagraphics volume the cover is in, or None when it is not located.
        page: The cover's page in that volume.
        link: The staged page the cover is built from, or empty.
        state_flag: How far along the cover ladder it is.
        has_issue_problem: Whether the cover's issue data is incomplete.
        problems: Everything found wrong with the cover's files.

    """

    display_title: str
    issue_title: str
    kind: str
    volume: int | None
    page: str
    link: str
    state_flag: str
    has_issue_problem: bool
    problems: list[str]


def has_issue_problem(cover: BarksCover) -> bool:
    """Return whether a cover's issue data is incomplete.

    True when `get_short_issue_title` has to fall back rather than name the issue
    properly: no `Issues` member (so the raw bibliography series name is used), an
    unnumbered issue, or a missing cover month or year. Only the first case occurs
    in `BARKS_COVERS` today - the others are flagged so they show up as soon as a
    newly authored cover has them.

    Args:
        cover: The cover record.

    Returns:
        True if any part of the cover's issue identity is missing.

    """
    return (
        cover.issue_name is None
        or cover.issue_number == -1
        or cover.issue_month == -1
        or cover.issue_year == -1
    )


def get_short_issue_title(cover: BarksCover) -> str:
    """Return a cover's issue as a short code plus its cover date.

    For example "FC 189 (Jun 1948)". Uses the same short issue code as the story
    report (`barks-fanta-info`), which is what makes the two tables scannable side
    by side. Mirrors `get_cover_display_title`'s fallbacks: the capitalized
    bibliography series name for the six cover-only albums with no `Issues` member,
    no number for an unnumbered issue, and the year alone for an undated one. The
    cover kind is left off - the Kind column already carries it.

    Args:
        cover: The cover record.

    Returns:
        The formatted short issue title.

    """
    if cover.issue_name is not None:
        issue = SHORT_ISSUE_NAME[cover.issue_name]
    else:
        issue = " ".join(word.capitalize() for word in cover.series_name.split())
    if cover.issue_number != -1:
        issue += f" {cover.issue_number}"

    if cover.issue_month != -1:
        date = f"{MONTH_AS_SHORT_STR[cover.issue_month]} {cover.issue_year}"
    else:
        date = str(cover.issue_year)

    return f"{issue} ({date})"


def has_incomplete_submitted_date(cover: BarksCover) -> bool:
    """Return whether any part of a cover's submitted date is unrecorded.

    `cover_submitted_sort_key` maps a -1 field to a sentinel that sorts last, so an
    incomplete date silently parks the cover at the end of submitted order rather
    than in its real place.

    Args:
        cover: The cover record.

    Returns:
        True if the submitted day, month or year is -1.

    """
    return cover.submitted_year == -1 or cover.submitted_month == -1 or cover.submitted_day == -1


def get_cover_problems(
    cover: BarksCover, staged_links: list[tuple[Path, Path]] | None
) -> list[str]:
    """Get the actionable problems for a cover, independently of its ladder state.

    Only the original-scan link is checked, in whichever extension it was staged under
    (`original_scan_slot`). The upscayled `.png` is absent for every cover and a cover
    builds fine without it, so reporting it would redden every located row permanently.
    Unlike one-pagers, a staged cover that is a real file rather than a symlink is not a
    problem - `barks-stage-covers --copy` is a supported mode.

    Args:
        cover: The cover record.
        staged_links: Its FANTA_02 `(link, source)` candidates, or None if unlocated.

    Returns:
        The problem codes, in a stable order.

    """
    problems = []

    if staged_links is not None:
        # By suffix until a `.png` cover fix showed up: the slot takes the source's
        # extension, so such a cover matched no `.jpg` and read as permanently unstaged.
        slot = original_scan_slot(staged_links)
        if slot is None or not slot.exists():
            problems.append(LINK_PROBLEM)

    if has_incomplete_submitted_date(cover):
        problems.append(DATE_PROBLEM)

    return problems


def get_cover_row(cover: BarksCover, staged_links: list[tuple[Path, Path]] | None) -> CoverRow:
    """Build the table row for one cover.

    A cover is `C` when `COVER_LOCATIONS` gives it a real (volume, page) - both > 0 -
    and `X` otherwise.

    Args:
        cover: The cover record.
        staged_links: Its FANTA_02 `(link, source)` candidates, or None if unlocated.

    Returns:
        The row's display fields.

    """
    location = get_cover_location(cover)
    if location is None:
        state_flag = NOT_CONFIGURED_FLAG
        volume = None
        page_str = ""
    else:
        state_flag = CONFIGURED_FLAG
        volume, page = location
        page_str = get_page_str(page)

    return CoverRow(
        display_title=ENUM_TO_STR_TITLE[get_cover_title(cover)],
        issue_title=get_short_issue_title(cover),
        kind=cover.kind.name,
        volume=volume,
        page=page_str,
        link=get_staged_link_stem(staged_links),
        state_flag=state_flag,
        has_issue_problem=has_issue_problem(cover),
        problems=get_cover_problems(cover, staged_links),
    )


def get_cover_rows(
    comics_database: ComicsDatabase, volumes: list[int], state_filter: list[str]
) -> list[CoverRow]:
    """Build the table rows for the requested covers.

    Args:
        comics_database: The comics database.
        volumes: Restrict to these Fantagraphics volumes; empty means all.
        state_filter: Keep only rows whose state flag is in this list.

    Returns:
        The rows, in `BARKS_COVERS` (submitted-date) order.

    """
    staged_links_by_title = get_staged_links_by_title(comics_database)
    rows = [
        get_cover_row(cover, staged_links_by_title.get(get_cover_title(cover)))
        for cover in BARKS_COVERS
    ]

    return filter_rows(rows, volumes, state_filter)


app = typer.Typer()


@app.command(help="Barks cover configured state")
def main(
    volumes_str: VolumesArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    state: str = "",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    volumes = list(intspan(volumes_str))
    state_filter = get_state_filter(state, COVER_STATE_FLAGS)

    comics_database = ComicsDatabase()
    rows = get_cover_rows(comics_database, volumes, state_filter)

    table = get_report_table(
        ["Title", "Issue", "Kind"],
        (
            (
                [
                    row.display_title,
                    # In the problem colour when the issue data is incomplete.
                    Text(row.issue_title, style=PROBLEM_STYLE if row.has_issue_problem else ""),
                    row.kind,
                ],
                row,
            )
            for row in rows
        ),
        DONE_FLAG,
    )

    print_collection_report(table, comics_database, COLLECTION_TITLE)


if __name__ == "__main__":
    app()
