"""Report the build state of the Fantagraphics stories in a volume.

Covers only real stories. One-pagers, individual covers and the two synthetic
collections ("All One-Pagers", "All Covers") are excluded - they have their own
reports, `barks-one-pager-info` and `barks-cover-info`, because their workflows
and their per-title data are nothing like a story's.
"""

from dataclasses import dataclass

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
    BUILD_STATE_FLAGS,
    BUILT_FLAG,
    EMPTY_FLAG,
    FIXES_FLAG,
    NOT_CONFIGURED_FLAG,
    get_build_state_flag,
    get_state_filter,
    has_fixes,
)

APP_LOGGING_NAME = "ifan"


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
    display_title: str
    fixes_flag: str
    build_state_flag: str
    num_pages: int
    page_list: str
    has_front: bool
    num_splashes: int


def get_title_flags(
    comics_database: ComicsDatabase,
    fixes_filter: list[str],
    built_filter: list[str],
    issue_titles_info_list: list[tuple[str, str, FantaComicBookInfo, bool]],
) -> tuple[dict[str, Flags], int, int]:
    max_ttl_len = 0
    max_issue_ttl_len = 0
    ttl_flags = {}

    for issue_ttl_info in issue_titles_info_list:
        ttl = issue_ttl_info[0]
        issue_ttl = issue_ttl_info[1]
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
            flags = Flags(
                display_ttl,
                FIXES_FLAG if has_fixes(comic_book) else EMPTY_FLAG,
                get_build_state_flag(comic_book),
                num_pgs,
                ", ".join(get_abbrev_jpg_page_list(comic_book)).replace(" - ", "-"),
                get_has_front(comic_book),
                get_num_splashes(comic_book),
            )

        if flags.fixes_flag not in fixes_filter:
            continue
        if flags.build_state_flag not in built_filter:
            continue

        max_ttl_len = max(max_ttl_len, len(flags.display_title))
        max_issue_ttl_len = max(max_issue_ttl_len, len(issue_ttl))

        ttl_flags[ttl] = flags

    return ttl_flags, max_ttl_len, max_issue_ttl_len


def get_fixes_filter(fixes_arg: str) -> list[str]:
    if not fixes_arg:
        return [EMPTY_FLAG, FIXES_FLAG]

    filt = [fixes_arg]
    if not set(filt).issubset(set(FIXES_FLAG)):
        msg = f'Not a valid fixes filter: "{filt}".'
        raise RuntimeError(msg)

    return filt


app = typer.Typer()


@app.command(help="Fantagraphics info")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    fixes: str = "",
    built: str = "",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    if volumes_str and title_str:
        msg = "Options --volume and --title are mutually exclusive."
        raise typer.BadParameter(msg)

    volumes = list(intspan(volumes_str))

    comics_database = ComicsDatabase()

    fixes_filter = get_fixes_filter(fixes)
    built_filter = get_state_filter(built, BUILD_STATE_FLAGS)
    display_volumes = not volumes or len(volumes) > 1

    title_enum = STR_TITLE_TO_ENUM.get(title_str) if title_str else None
    if title_enum is not None and not is_story_title(title_enum):
        msg = (
            f'Title "{title_str}" is a one-pager, a cover or a collection.'
            f" Use barks-one-pager-info or barks-cover-info instead."
        )
        raise RuntimeError(msg)
    if title_enum is not None and title_enum not in ALL_FANTA_COMIC_BOOK_INFO:
        msg = f'Title "{title_str}" has no Fantagraphics volume info.'
        raise RuntimeError(msg)

    titles_and_info = get_titles_and_info(
        comics_database, volumes, title_str, configured_only=False
    )
    titles_and_info = get_titles_and_info_sorted_by_submission_date(titles_and_info)
    issue_titles_info = get_issue_titles(comics_database, titles_and_info)

    title_flags, _, _ = get_title_flags(
        comics_database, fixes_filter, built_filter, issue_titles_info
    )

    console = Console()
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
                flags.build_state_flag,
                f"{flags.num_pages} pp",
                f"f:{1 if flags.has_front else 0}",
                f"s:{flags.num_splashes}",
                flags.page_list,
            ]
        )

        style = "orange1" if flags.build_state_flag != BUILT_FLAG else None
        table.add_row(*row, style=style)

    console.print(table)


if __name__ == "__main__":
    app()
