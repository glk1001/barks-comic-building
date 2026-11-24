"""Report the build state of the Fantagraphics stories in a volume.

Covers only real stories. One-pagers, individual covers and the two synthetic
collections ("All One-Pagers", "All Covers") are excluded - they have their own
reports, `barks-one-pager-info` and `barks-cover-info`, because their workflows
and their per-title data are nothing like a story's.
"""

from dataclasses import dataclass
from typing import Annotated

import typer
from barks_fantagraphics.barks_titles import STR_TITLE_TO_ENUM, Titles
from barks_fantagraphics.comic_book import (
    get_abbrev_jpg_page_list,
    get_has_front,
    get_num_splashes,
    get_total_num_pages,
)
from barks_fantagraphics.comic_book_info import (
    COVERS_SET,
    ONE_PAGERS,
    is_covers_collection,
    is_one_pager_collection,
)
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_issue_titles, get_titles_and_info
from barks_fantagraphics.comics_utils import get_titles_and_info_sorted_by_submission_date
from barks_fantagraphics.fanta_comics_info import ALL_FANTA_COMIC_BOOK_INFO, FantaComicBookInfo
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from intspan import intspan
from rich.console import Console
from rich.table import Table

from barks_comic_building.cli_setup import init_logging
from barks_comic_building.query.build_state import (
    BUILT_FLAG,
    EMPTY_FLAG,
    FAULT_FLAG,
    FIXES_FLAG,
    NOT_CONFIGURED_FLAG,
    PROBLEM_STYLE,
    STORY_STATE_FLAGS,
    get_state_filter,
    get_title_state,
)

APP_LOGGING_NAME = "ifan"

# What `--fixes` takes: the titles with a fixes file, or the titles without one.
WITH_FIXES_ARG = FIXES_FLAG
NO_FIXES_ARG = "none"


def is_story_title(title: Titles) -> bool:
    """Return whether a title is a real story this report should include.

    One-pagers and individual covers sit outside the main story sequence, and the
    two synthetic collections are assembled from them, so all three are reported
    elsewhere.

    Args:
        title: The title to test.

    Returns:
        True if the title is a real Fantagraphics story.

    """
    return (
        title not in ONE_PAGERS
        and title not in COVERS_SET
        and not is_one_pager_collection(title)
        and not is_covers_collection(title)
    )


@dataclass
class Flags:
    """What the report shows for one title.

    Attributes:
        display_title: The title, in brackets when it is not Barks's own.
        fixes_flag: `FIXES_FLAG` for a title with a fixes file, else `EMPTY_FLAG`.
        build_state_flag: How far up the build ladder the title is.
        num_pages: The title's page count, or -1 when it is not configured.
        page_list: The title's scan pages, abbreviated.
        has_front: Whether the title has a front page.
        num_splashes: How many pages the ini file types as a splash.
        fault: The file rule the title breaks, when its state is `FAULT_FLAG`.

    """

    display_title: str
    fixes_flag: str
    build_state_flag: str
    num_pages: int
    page_list: str
    has_front: bool
    num_splashes: int
    fault: str = ""


def get_title_flags(
    comics_database: ComicsDatabase,
    fixes_filter: list[str],
    built_filter: list[str],
    issue_titles_info_list: list[tuple[str, str, FantaComicBookInfo, bool]],
) -> dict[str, Flags]:
    """Return the report's row for each story that passes the filters.

    Args:
        comics_database: The database to open each configured title in.
        fixes_filter: Keep only the titles whose fixes flag is one of these.
        built_filter: Keep only the titles whose build state flag is one of these.
        issue_titles_info_list: Each title with its issue title, its Fantagraphics info
            and whether it is configured, as `get_issue_titles` gives them.

    Returns:
        The rows by title, in the order given. One-pagers, covers and the collections
        are left out.

    Raises:
        RuntimeError: If a configured title has no pages.

    """
    ttl_flags = {}

    for issue_ttl_info in issue_titles_info_list:
        ttl = issue_ttl_info[0]
        ttl_info = issue_ttl_info[2]
        is_configured = issue_ttl_info[3]

        if not is_story_title(STR_TITLE_TO_ENUM[ttl]):
            continue

        if not is_configured:
            display_ttl = ttl if ttl_info.comic_book_info.is_barks_title else f"({ttl})"
            flags = Flags(
                display_ttl,
                EMPTY_FLAG,
                NOT_CONFIGURED_FLAG,
                num_pages=-1,
                page_list="",
                has_front=False,
                num_splashes=0,
            )
        else:
            comic_book = comics_database.get_comic_book(ttl)

            display_ttl = ttl if comic_book.is_barks_title() else f"({ttl})"
            num_pgs = get_total_num_pages(comic_book)
            if num_pgs <= 0:
                msg = f'For title "{ttl}", the page count is too small.'
                raise RuntimeError(msg)
            state = get_title_state(comic_book)
            flags = Flags(
                display_ttl,
                FIXES_FLAG if state.has_fixes else EMPTY_FLAG,
                state.flag,
                num_pgs,
                ", ".join(get_abbrev_jpg_page_list(comic_book)).replace(" - ", "-"),
                get_has_front(comic_book),
                get_num_splashes(comic_book),
                fault=state.fault or "",
            )

        if flags.fixes_flag not in fixes_filter:
            continue
        if flags.build_state_flag not in built_filter:
            continue

        ttl_flags[ttl] = flags

    return ttl_flags


def get_fixes_filter(fixes_arg: str) -> list[str]:
    """Parse the `--fixes` option into the fixes flags to keep.

    Args:
        fixes_arg: The option as given: `WITH_FIXES_ARG` for the titles that have a
            fixes file, `NO_FIXES_ARG` for the titles that have none, or empty for both.

    Returns:
        The fixes flags a title must have one of.

    Raises:
        typer.BadParameter: If the option is anything else.

    """
    if not fixes_arg:
        return [EMPTY_FLAG, FIXES_FLAG]
    if fixes_arg == WITH_FIXES_ARG:
        return [FIXES_FLAG]
    if fixes_arg == NO_FIXES_ARG:
        return [EMPTY_FLAG]

    msg = f'--fixes must be "{WITH_FIXES_ARG}" or "{NO_FIXES_ARG}": "{fixes_arg}".'
    raise typer.BadParameter(msg)


def check_story_title(title_str: str) -> None:
    """Check that a `--title` option names a story this report can show.

    Args:
        title_str: The option as given.

    Raises:
        typer.BadParameter: If it is not a title, is a title one of the other reports
            covers, or is a title in no Fantagraphics volume.

    """
    title_enum = STR_TITLE_TO_ENUM.get(title_str)
    if title_enum is None:
        msg = f'"{title_str}" is not a title. Use barks-verify-title to find the one meant.'
        raise typer.BadParameter(msg)
    if not is_story_title(title_enum):
        msg = (
            f'Title "{title_str}" is a one-pager, a cover or a collection.'
            f" Use barks-one-pager-info or barks-cover-info instead."
        )
        raise typer.BadParameter(msg)
    if title_enum not in ALL_FANTA_COMIC_BOOK_INFO:
        msg = f'Title "{title_str}" has no Fantagraphics volume info.'
        raise typer.BadParameter(msg)


def get_report_table(
    issue_titles_info: list[tuple[str, str, FantaComicBookInfo, bool]],
    title_flags: dict[str, Flags],
    *,
    display_volumes: bool,
) -> Table:
    """Return the report's table: one row for each title that has flags.

    Args:
        issue_titles_info: Every title asked about, in the order to list them.
        title_flags: The row of each title that passed the filters.
        display_volumes: Whether to give each title's volume its own column.

    Returns:
        The table, a title that is not built yet in the not-done colour.

    """
    table = Table()
    table.add_column("Title")
    table.add_column("Issue")
    if display_volumes:
        table.add_column("Vol")
    table.add_column("Fix")
    table.add_column("State")
    table.add_column("Pages", justify="right")
    table.add_column("Front")
    table.add_column("Splash")
    table.add_column("Jpgs")

    for issue_title_info in issue_titles_info:
        title = issue_title_info[0]
        comic_book_info = issue_title_info[2]

        if title not in title_flags:
            continue

        issue_title = issue_title_info[1]
        flags = title_flags[title]

        row = [
            flags.display_title,
            issue_title,
        ]
        if display_volumes:
            row.append(comic_book_info.fantagraphics_volume)

        row.extend(
            [
                flags.fixes_flag,
                (
                    f"[{PROBLEM_STYLE}]{flags.build_state_flag}[/]"
                    if flags.build_state_flag == FAULT_FLAG
                    else flags.build_state_flag
                ),
                f"{flags.num_pages} pp",
                f"f:{1 if flags.has_front else 0}",
                f"s:{flags.num_splashes}",
                flags.page_list,
            ]
        )

        style = "orange1" if flags.build_state_flag != BUILT_FLAG else None
        table.add_row(*row, style=style)

    return table


STORY_STATES_HELP = ",".join(STORY_STATE_FLAGS)

app = typer.Typer()


@app.command(help="Fantagraphics info")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    fixes: Annotated[
        str,
        typer.Option(
            help=f'Only titles with fixes ("{WITH_FIXES_ARG}") or without ("{NO_FIXES_ARG}")'
        ),
    ] = "",
    built: Annotated[
        str,
        typer.Option(help=f"Only titles in these states, comma-separated: {STORY_STATES_HELP}"),
    ] = "",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    if volumes_str and title_str:
        msg = "Options --volume and --title are mutually exclusive."
        raise typer.BadParameter(msg)
    if not volumes_str and not title_str:
        msg = "One of the options --volume and --title is required."
        raise typer.BadParameter(msg)

    try:
        volumes = list(intspan(volumes_str))
    except ValueError as e:
        msg = f'--volume is not a list of volumes: "{volumes_str}".'
        raise typer.BadParameter(msg) from e

    fixes_filter = get_fixes_filter(fixes)
    built_filter = get_state_filter(built, STORY_STATE_FLAGS)
    display_volumes = not volumes or len(volumes) > 1

    if title_str:
        check_story_title(title_str)

    comics_database = ComicsDatabase()

    titles_and_info = get_titles_and_info(
        comics_database, volumes, title_str, configured_only=False
    )
    titles_and_info = get_titles_and_info_sorted_by_submission_date(titles_and_info)
    issue_titles_info = get_issue_titles(comics_database, titles_and_info)

    title_flags = get_title_flags(comics_database, fixes_filter, built_filter, issue_titles_info)

    console = Console()
    table = get_report_table(issue_titles_info, title_flags, display_volumes=display_volumes)

    console.print(table)

    for title, flags in title_flags.items():
        if flags.fault:
            # Not markup: a fault quotes file paths, and a "[" in one is not a style.
            console.print(
                f'{FAULT_FLAG} "{title}": {flags.fault}', style=PROBLEM_STYLE, markup=False
            )


if __name__ == "__main__":
    app()
