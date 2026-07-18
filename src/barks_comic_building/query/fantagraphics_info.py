from dataclasses import dataclass
from pathlib import Path

import typer
from barks_fantagraphics.barks_payments import BARKS_PAYMENTS
from barks_fantagraphics.barks_titles import ENUM_TO_STR_TITLE, STR_TITLE_TO_ENUM, Titles
from barks_fantagraphics.comic_book import (
    ComicBook,
    ModifiedType,
    get_abbrev_jpg_page_list,
    get_has_front,
    get_num_splashes,
    get_page_str,
    get_total_num_pages,
)
from barks_fantagraphics.comic_book_info import (
    BARKS_TITLE_INFO,
    ONE_PAGERS,
    get_one_pager_fanta_vol_and_page,
    is_one_pager_located,
)
from barks_fantagraphics.comics_consts import (
    PNG_INSET_DIR,
    PNG_INSET_EXT,
    RESTORABLE_PAGE_TYPES,
)
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_issue_titles, get_titles_and_info
from barks_fantagraphics.comics_utils import (
    dest_file_is_older_than_srce,
    get_max_timestamp,
    get_timestamp,
    get_titles_and_info_sorted_by_submission_date,
)
from barks_fantagraphics.fanta_comics_info import (
    ALL_FANTA_COMIC_BOOK_INFO,
    HAND_RESTORED_TITLES,
    SERIES_ONE_PAGERS,
    FantaComicBookInfo,
)
from comic_utils.comic_consts import PNG_FILE_EXT
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from intspan import intspan
from loguru import logger
from rich.console import Console
from rich.table import Table

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "ifan"

EMPTY_FLAG = " "
FIXES_FLAG = "F"

NOT_CONFIGURED_FLAG = "X"
CONFIGURED_FLAG = "C"
PAYMENTS_FLAG = "$"
UPSCAYLED_FLAG = "U"
RESTORED_FLAG = "R"
PANELLED_FLAG = "P"
INSET_FLAG = "I"
BUILT_FLAG = "B"

BUILD_STATE_FLAGS = [
    NOT_CONFIGURED_FLAG,
    CONFIGURED_FLAG,
    PAYMENTS_FLAG,
    UPSCAYLED_FLAG,
    RESTORED_FLAG,
    PANELLED_FLAG,
    INSET_FLAG,
    BUILT_FLAG,
]


def is_upscayled(comic: ComicBook) -> bool:
    if comic.get_ini_title() in HAND_RESTORED_TITLES:
        return True

    return all_files_exist(
        [f[0] for f in comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)]
    )


def is_restored(comic: ComicBook) -> bool:
    if comic.get_ini_title() in HAND_RESTORED_TITLES:
        return True

    return all_files_exist(comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES))


def has_inset_file(comic: ComicBook) -> bool:
    return comic.intro_inset_file.is_file()


def has_fixes(comic: ComicBook) -> bool:
    mods = [
        f[1]
        for f in comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
        if f[1] != ModifiedType.ORIGINAL
    ]
    if any(mods):
        return True

    mods = [
        f[1]
        for f in comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)
        if f[1] != ModifiedType.ORIGINAL
    ]
    return any(mods)


def has_panel_bounds(comic: ComicBook) -> bool:
    if not is_restored(comic):
        return False
    if not all_files_exist(comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES)):
        return False
    if comic.get_ini_title() in HAND_RESTORED_TITLES:
        return True

    restored_files = comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)
    panel_segments_files = comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES)

    for restored_file, panel_segments_file in zip(
        restored_files, panel_segments_files, strict=True
    ):
        if dest_file_is_older_than_srce(restored_file, panel_segments_file):
            logger.debug(
                f'Panels segments file "{panel_segments_file}" is'
                f' out of date WRT restored file "{restored_file}".'
            )
            return False

    return True


def is_built(comic: ComicBook) -> bool:  # noqa: PLR0911
    if not has_panel_bounds(comic):
        return False
    if not is_restored(comic):
        return False

    panel_segments_files = comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES)
    max_panel_segments_timestamp = get_max_timestamp(panel_segments_files)
    zip_file = comic.get_dest_comic_zip()
    if not zip_file.is_file():
        logger.debug(f'No zip file: "{zip_file}".')
        return False
    zip_file_timestamp = get_timestamp(zip_file)

    if zip_file_timestamp < max_panel_segments_timestamp:
        logger.debug(f'Zip file is out of date WRT panel segments files: "{zip_file}".')
        return False

    series_comic_zip_symlink = comic.get_dest_series_comic_zip_symlink()
    if not series_comic_zip_symlink.is_symlink():
        logger.debug(f'No series symlink is zip file: "{series_comic_zip_symlink}".')
        return False
    series_comic_zip_symlink_timestamp = get_timestamp(series_comic_zip_symlink)

    if series_comic_zip_symlink_timestamp < zip_file_timestamp:
        logger.debug(f'Series symlink is out of date WRT zip file: "{series_comic_zip_symlink}".')
        return False

    year_comic_zip_symlink = comic.get_dest_year_comic_zip_symlink()
    if not year_comic_zip_symlink.is_symlink():
        logger.debug(f'No year symlink is zip file: "{year_comic_zip_symlink}".')
        return False
    year_comic_zip_symlink_timestamp = get_timestamp(series_comic_zip_symlink)

    if year_comic_zip_symlink_timestamp < zip_file_timestamp:
        logger.debug(f'Year symlink is out of date WRT zip file: "{year_comic_zip_symlink}".')
        return False

    logger.debug(f'"{comic.ini_file}" has been built.')

    return True


def all_files_exist(file_list: list[Path]) -> bool:
    if not file_list:
        return False

    return all(file.is_file() for file in file_list)


def get_build_state_flag(comic: ComicBook) -> str:
    flag = CONFIGURED_FLAG

    restored = is_restored(comic)
    panels = has_panel_bounds(comic)

    if is_built(comic):
        flag = BUILT_FLAG
    elif has_inset_file(comic) and restored and panels:
        flag = INSET_FLAG
    elif panels:
        flag = PANELLED_FLAG
    elif restored:
        flag = RESTORED_FLAG
    elif is_upscayled(comic):
        flag = UPSCAYLED_FLAG

    return flag


@dataclass
class Flags:
    display_title: str
    fixes_flag: str
    build_state_flag: str
    num_pages: int
    page_list: str
    has_front: bool
    num_splashes: int


def get_missing_one_pager_fanta_info(title: Titles) -> FantaComicBookInfo:
    """Make stand-in Fantagraphics info for a one-pager absent from the volume data.

    Unlocated one-pagers have no `SERIES_INFO` entry (their Fantagraphics volume is
    not yet known), so they are missing from `ALL_FANTA_COMIC_BOOK_INFO` and would
    otherwise never get a table row.

    Args:
        title: The one-pager title.

    Returns:
        Fantagraphics info with just enough filled in for a table row (no volume).

    """
    return FantaComicBookInfo(
        comic_book_info=BARKS_TITLE_INFO[title],
        colorist="",
        series_name=SERIES_ONE_PAGERS,
    )


def get_missing_one_pager_titles_and_info() -> list[tuple[str, FantaComicBookInfo]]:
    """Get title/info rows for one-pagers absent from the Fantagraphics volume data.

    Returns:
        The (title, stand-in info) pairs, in `ONE_PAGERS` (chronological) order.

    """
    return [
        (ENUM_TO_STR_TITLE[title], get_missing_one_pager_fanta_info(title))
        for title in ONE_PAGERS
        if title not in ALL_FANTA_COMIC_BOOK_INFO
    ]


def get_one_pager_flags(
    comics_database: ComicsDatabase, ttl: str, ttl_info: FantaComicBookInfo
) -> Flags:
    """Get the display flags for a one-pager title.

    One-pagers have no per-title ini file, so their state comes from a strict
    workflow ladder instead: `X` (no proper `ONE_PAGER_LOCATIONS` entry) -> `C`
    (located) -> `$` (Barks payments info added) -> `I` (inset file present) ->
    `U` (upscayled volume page present) -> `R` (restored volume page present).
    A state is shown only when every earlier step is fulfilled, so - as with
    non-one-pagers - `R` guarantees the whole workflow is done.

    Args:
        comics_database: The comics database.
        ttl: The one-pager title string.
        ttl_info: The Fantagraphics info for the title.

    Returns:
        The flags for the one-pager's table row.

    """
    title = STR_TITLE_TO_ENUM[ttl]
    display_ttl = ttl if ttl_info.comic_book_info.is_barks_title else f"({ttl})"

    if not is_one_pager_located(title):
        build_state_flg = NOT_CONFIGURED_FLAG
        page_lst = ""
    else:
        volume, page = get_one_pager_fanta_vol_and_page(title)
        assert volume is not None
        assert page is not None
        page_lst = get_page_str(page)

        upscayled_dir = comics_database.get_fantagraphics_upscayled_volume_image_dir(volume)
        restored_dir = comics_database.get_fantagraphics_restored_volume_image_dir(volume)
        ladder = [
            (PAYMENTS_FLAG, BARKS_PAYMENTS[title].payment > 0),
            (INSET_FLAG, (PNG_INSET_DIR / (ttl + PNG_INSET_EXT)).is_file()),
            (UPSCAYLED_FLAG, (upscayled_dir / (page_lst + PNG_FILE_EXT)).is_file()),
            (RESTORED_FLAG, (restored_dir / (page_lst + PNG_FILE_EXT)).is_file()),
        ]
        build_state_flg = CONFIGURED_FLAG
        for flag, step_done in ladder:
            if not step_done:
                break
            build_state_flg = flag

    return Flags(
        display_ttl,
        EMPTY_FLAG,
        build_state_flg,
        num_pages=1,
        page_list=page_lst,
        has_front=False,
        num_splashes=0,
    )


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

        if STR_TITLE_TO_ENUM[ttl] in ONE_PAGERS:
            flags = get_one_pager_flags(comics_database, ttl, ttl_info)
        elif not is_configured:
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


def get_built_filter(built_arg: str) -> list[str]:
    if not built_arg:
        return BUILD_STATE_FLAGS

    filt = built_arg.split(",")
    if not set(filt).issubset(set(BUILD_STATE_FLAGS)):
        msg = f'Not a valid built filter: "{filt}".'
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
    built_filter = get_built_filter(built)
    display_volumes = not volumes or len(volumes) > 1

    title_enum = STR_TITLE_TO_ENUM.get(title_str) if title_str else None
    if title_enum is not None and title_enum not in ALL_FANTA_COMIC_BOOK_INFO:
        if title_enum not in ONE_PAGERS:
            msg = f'Title "{title_str}" has no Fantagraphics volume info.'
            raise RuntimeError(msg)
        titles_and_info = [(title_str, get_missing_one_pager_fanta_info(title_enum))]
    else:
        titles_and_info = get_titles_and_info(
            comics_database, volumes, title_str, configured_only=False
        )
        titles_and_info = get_titles_and_info_sorted_by_submission_date(titles_and_info)
        if not title_str:
            titles_and_info += get_missing_one_pager_titles_and_info()
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
            row.append(str(comic_book_info.fantagraphics_volume))

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

        done_flag = RESTORED_FLAG if STR_TITLE_TO_ENUM[title] in ONE_PAGERS else BUILT_FLAG
        style = "orange1" if flags.build_state_flag != done_flag else None
        table.add_row(*row, style=style)

    console.print(table)


if __name__ == "__main__":
    app()
