"""Report the build state of the Barks one-pagers.

One-pagers have no per-title ini file - nothing reads one, because the reader opens
a one-pager as a page of the "All One-Pagers" collection rather than as a comic of
its own - so their state comes from a strict workflow ladder over the files in their
host Fantagraphics volume rather than from a `ComicBook`. Every one-pager is listed,
located or not.

The `State` column reports the ladder, which stops at the first unmet rung. The
`Problem` column reports everything else that is actionable, independently of the
ladder, so a bookkeeping gap (a missing payment value, say) cannot hide the fact
that a one-pager is missing a staged artifact.

At the bottom the report says whether the synthetic "All One-Pagers" collection -
which is assembled from the located one-pagers by `barks-stage-one-pagers` and then
built like any other title - is currently built, and if not, why.
"""

from dataclasses import dataclass
from pathlib import Path

import typer
from barks_fantagraphics.barks_payments import BARKS_PAYMENTS
from barks_fantagraphics.barks_titles import ENUM_TO_STR_TITLE, STR_TITLE_TO_ENUM, Titles
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comic_book_info import (
    BARKS_TITLE_INFO,
    ONE_PAGERS,
    get_filename_from_title,
    get_one_pager_fanta_vol_and_page,
    get_one_pager_issue_page,
    is_one_pager_located,
)
from barks_fantagraphics.comics_consts import PNG_INSET_DIR, PNG_INSET_EXT
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.comic_consts import PNG_FILE_EXT
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from intspan import intspan
from rich.console import Console
from rich.table import Table
from rich.text import Text

from barks_comic_building.build.stage_one_pagers import get_staged_links_by_title
from barks_comic_building.cli_setup import init_logging
from barks_comic_building.query.build_state import (
    BUILT_STYLE,
    CONFIGURED_FLAG,
    INSET_FLAG,
    NOT_CONFIGURED_FLAG,
    NOT_DONE_STYLE,
    PAYMENTS_FLAG,
    PROBLEM_STYLE,
    RESTORED_FLAG,
    UPSCAYLED_FLAG,
    get_build_blocker,
    get_staged_link_stem,
    get_state_filter,
)

APP_LOGGING_NAME = "i1pg"

COLLECTION_TITLE = ENUM_TO_STR_TITLE[Titles.ALL_ONE_PAGERS]

# The one-pager ladder, in order. A one-pager is reported at the last rung whose
# every predecessor is also fulfilled, so `R` means the whole workflow is done.
ONE_PAGER_STATE_FLAGS = [
    NOT_CONFIGURED_FLAG,
    CONFIGURED_FLAG,
    PAYMENTS_FLAG,
    INSET_FLAG,
    UPSCAYLED_FLAG,
    RESTORED_FLAG,
]

DONE_FLAG = RESTORED_FLAG

# Problem codes. Independent of the ladder - each is reported whenever it holds,
# whatever the row's state, so nothing is masked by an earlier unmet rung.
LINK_PROBLEM = "link"  # a FANTA_01 staged artifact is absent
COPY_PROBLEM = "copy"  # a staged artifact is a real file, not a symlink
PAGE_PROBLEM = "page"  # located, but no original-issue page recorded
INSET_PROBLEM = "inset"  # no inset file, so the reader shows its emergency placeholder


@dataclass
class OnePagerRow:
    display_title: str
    issue_title: str
    volume: int | None
    page: str
    link: str
    state_flag: str
    problems: list[str]


def get_one_pager_state_flag(comics_database: ComicsDatabase, title: Titles) -> tuple[str, str]:
    """Get the state flag and volume page for a one-pager.

    The ladder is `X` (no proper `ONE_PAGER_LOCATIONS` entry) -> `C` (located) ->
    `$` (Barks payments info added) -> `I` (inset file present) -> `U` (upscayled
    volume page present) -> `R` (restored volume page present). A state is returned
    only when every earlier step is fulfilled, so - as for a story title - `R`
    guarantees the whole workflow is done.

    Args:
        comics_database: The comics database.
        title: The one-pager title.

    Returns:
        The state flag, and the one-pager's page within its volume ("" if unlocated).

    """
    if not is_one_pager_located(title):
        return NOT_CONFIGURED_FLAG, ""

    volume, page = get_one_pager_fanta_vol_and_page(title)
    assert volume is not None
    assert page is not None
    page_str = get_page_str(page)

    upscayled_dir = comics_database.get_fantagraphics_upscayled_volume_image_dir(volume)
    restored_dir = comics_database.get_fantagraphics_restored_volume_image_dir(volume)
    ladder = [
        (PAYMENTS_FLAG, BARKS_PAYMENTS[title].payment > 0),
        (INSET_FLAG, has_inset_file(title)),
        (UPSCAYLED_FLAG, (upscayled_dir / (page_str + PNG_FILE_EXT)).is_file()),
        (RESTORED_FLAG, (restored_dir / (page_str + PNG_FILE_EXT)).is_file()),
    ]

    state_flag = CONFIGURED_FLAG
    for flag, step_done in ladder:
        if not step_done:
            break
        state_flag = flag

    return state_flag, page_str


def get_short_issue_title(title: Titles) -> str:
    """Return a one-pager's issue as a short code plus its original-issue page.

    For example "FC 178, p. 35". Uses the same short issue code as the story report
    (`barks-fanta-info`), which is what makes the two tables scannable side by side.
    The page is what tells co-published one-pagers apart - three of them share
    Four Color #178 - so it is kept, and dropped only when it is not recorded.

    Args:
        title: The one-pager title.

    Returns:
        The formatted short issue title.

    """
    short_issue = BARKS_TITLE_INFO[title].get_short_issue_title()
    issue_page = get_one_pager_issue_page(title)

    return f"{short_issue}, p. {issue_page}" if issue_page is not None else short_issue


def has_inset_file(title: Titles) -> bool:
    """Return whether a title has an inset file the reader can use.

    Resolved exactly as `ReaderFilePaths.get_comic_inset_file` does - by mapping the
    title to a filename - because a missing inset is not an error there: the reader
    silently substitutes its emergency placeholder.

    Args:
        title: The title to check.

    Returns:
        True if the title's inset file exists.

    """
    return (PNG_INSET_DIR / get_filename_from_title(title, PNG_INSET_EXT)).is_file()


def get_one_pager_problems(
    title: Titles, staged_links: list[tuple[Path, Path]] | None
) -> list[str]:
    """Get the actionable problems for a one-pager, independently of its ladder state.

    Only reports what can be acted on. An unlocated one-pager has no staged links and
    no recorded original-issue page by definition, so neither is reported against it -
    its `X` state already says the location table is the thing to fill in.

    Args:
        title: The one-pager title.
        staged_links: Its FANTA_01 `(link, source)` candidates, or None if unlocated.

    Returns:
        The problem codes, in a stable order.

    """
    problems = []

    if staged_links is not None:
        missing = [link for link, _ in staged_links if not link.exists()]
        if missing:
            problems.append(f"{LINK_PROBLEM}({len(missing)})")
        # `barks-stage-one-pagers` only ever symlinks, so a real file here was not
        # put there by the stager and has stopped tracking its source volume.
        copied = [link for link, _ in staged_links if link.exists() and not link.is_symlink()]
        if copied:
            problems.append(f"{COPY_PROBLEM}({len(copied)})")
        if get_one_pager_issue_page(title) is None:
            problems.append(PAGE_PROBLEM)

    if not has_inset_file(title):
        problems.append(INSET_PROBLEM)

    return problems


def get_one_pager_row(
    comics_database: ComicsDatabase,
    title: Titles,
    staged_links: list[tuple[Path, Path]] | None,
) -> OnePagerRow:
    """Build the table row for one one-pager.

    Args:
        comics_database: The comics database.
        title: The one-pager title.
        staged_links: Its FANTA_01 `(link, source)` candidates, or None if unlocated.

    Returns:
        The row's display fields.

    """
    ttl = ENUM_TO_STR_TITLE[title]
    display_ttl = ttl if BARKS_TITLE_INFO[title].is_barks_title else f"({ttl})"
    state_flag, page_str = get_one_pager_state_flag(comics_database, title)
    volume, _ = get_one_pager_fanta_vol_and_page(title)

    return OnePagerRow(
        display_title=display_ttl,
        issue_title=get_short_issue_title(title),
        volume=volume,
        page=page_str,
        link=get_staged_link_stem(staged_links),
        state_flag=state_flag,
        problems=get_one_pager_problems(title, staged_links),
    )


def get_one_pager_rows(
    comics_database: ComicsDatabase,
    volumes: list[int],
    title_str: str,
    state_filter: list[str],
) -> list[OnePagerRow]:
    """Build the table rows for the requested one-pagers.

    Args:
        comics_database: The comics database.
        volumes: Restrict to these Fantagraphics volumes; empty means all.
        title_str: Restrict to this single one-pager; empty means all.
        state_filter: Keep only rows whose state flag is in this list.

    Returns:
        The rows, in `ONE_PAGERS` (chronological) order.

    Raises:
        RuntimeError: If `title_str` is not a one-pager.

    """
    if title_str:
        title = STR_TITLE_TO_ENUM.get(title_str)
        if title is None or title not in ONE_PAGERS:
            msg = f'Title "{title_str}" is not a one-pager.'
            raise RuntimeError(msg)
        titles = [title]
    else:
        titles = ONE_PAGERS

    staged_links_by_title = get_staged_links_by_title(comics_database)
    rows = [
        get_one_pager_row(comics_database, title, staged_links_by_title.get(title))
        for title in titles
    ]

    if volumes:
        rows = [row for row in rows if row.volume in volumes]

    return [row for row in rows if row.state_flag in state_filter]


def get_collection_state_text(comics_database: ComicsDatabase) -> tuple[str, str]:
    """Get the bottom-line text saying whether "All One-Pagers" is built.

    Args:
        comics_database: The comics database.

    Returns:
        The message and the rich style to print it in.

    """
    comic = comics_database.get_comic_book(COLLECTION_TITLE)
    blocker = get_build_blocker(comic)
    if blocker is None:
        return f'"{COLLECTION_TITLE}" is built.', BUILT_STYLE

    return f'"{COLLECTION_TITLE}" is NOT built - {blocker}.', NOT_DONE_STYLE


app = typer.Typer()


@app.command(help="Barks one-pager build state")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    state: str = "",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    if volumes_str and title_str:
        msg = "Options --volume and --title are mutually exclusive."
        raise typer.BadParameter(msg)

    volumes = list(intspan(volumes_str))
    state_filter = get_state_filter(state, ONE_PAGER_STATE_FLAGS)

    comics_database = ComicsDatabase()
    rows = get_one_pager_rows(comics_database, volumes, title_str, state_filter)

    table = Table()
    table.add_column("Title")
    table.add_column("Issue")
    table.add_column("Vol", justify="right")
    table.add_column("Jpgs", justify="right")
    table.add_column("Link", justify="right")
    table.add_column("State")
    table.add_column("Problem")

    for row in rows:
        style = NOT_DONE_STYLE if row.state_flag != DONE_FLAG else None
        table.add_row(
            row.display_title,
            row.issue_title,
            "" if row.volume is None else str(row.volume),
            row.page,
            row.link,
            row.state_flag,
            Text(",".join(row.problems), style=PROBLEM_STYLE),
            style=style,
        )

    console = Console()
    console.print(table)

    collection_text, collection_style = get_collection_state_text(comics_database)
    console.print(collection_text, style=collection_style)


if __name__ == "__main__":
    app()
