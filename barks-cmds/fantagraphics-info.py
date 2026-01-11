from dataclasses import dataclass
from pathlib import Path

import typer
from barks_fantagraphics.comic_book import (
    ComicBook,
    get_abbrev_jpg_page_list,
    get_has_front,
    get_num_splashes,
    get_total_num_pages,
)
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_issue_titles, get_titles_and_info
from barks_fantagraphics.comics_utils import (
    dest_file_is_older_than_srce,
    get_max_timestamp,
    get_timestamp,
    get_titles_and_info_sorted_by_submission_date,
)
from barks_fantagraphics.fanta_comics_info import FantaComicBookInfo
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from intspan import intspan
from loguru import logger
from loguru_config import LoguruConfig
from rich.console import Console
from rich.table import Table

APP_LOGGING_NAME = "ifan"

EMPTY_FLAG = " "
FIXES_FLAG = "F"

NOT_CONFIGURED_FLAG = "X"
CONFIGURED_FLAG = "C"
UPSCAYLED_FLAG = "U"
RESTORED_FLAG = "R"
PANELLED_FLAG = "P"
INSET_FLAG = "I"
BUILT_FLAG = "B"

BUILD_STATE_FLAGS = [
    NOT_CONFIGURED_FLAG,
    CONFIGURED_FLAG,
    UPSCAYLED_FLAG,
    RESTORED_FLAG,
    PANELLED_FLAG,
    INSET_FLAG,
    BUILT_FLAG,
]

app = typer.Typer()
log_level = ""


def is_upscayled(comic: ComicBook) -> bool:
    return all_files_exist(
        [f[0] for f in comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)]
    )


def is_restored(comic: ComicBook) -> bool:
    return all_files_exist(comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES))


def has_inset_file(comic: ComicBook) -> bool:
    return comic.intro_inset_file.is_file()


def has_fixes(comic: ComicBook) -> bool:
    mods = [f[1] for f in comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)]
    if any(mods):
        return True

    mods = [f[1] for f in comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)]
    return any(mods)


def has_panel_bounds(comic: ComicBook) -> bool:
    if not is_restored(comic):
        return False
    if not all_files_exist(comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES)):
        return False

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
        return False
    zip_file_timestamp = get_timestamp(zip_file)

    if zip_file_timestamp < max_panel_segments_timestamp:
        logger.debug(f'Zip file is out of date WRT panel segments files: "{zip_file}".')
        return False

    series_comic_zip_symlink = comic.get_dest_series_comic_zip_symlink()
    if not series_comic_zip_symlink.is_symlink():
        return False
    series_comic_zip_symlink_timestamp = get_timestamp(series_comic_zip_symlink)

    if series_comic_zip_symlink_timestamp < zip_file_timestamp:
        logger.debug(f'Series symlink is out of date WRT zip file: "{series_comic_zip_symlink}".')
        return False

    year_comic_zip_symlink = comic.get_dest_year_comic_zip_symlink()
    if not year_comic_zip_symlink.is_symlink():
        return False
    year_comic_zip_symlink_timestamp = get_timestamp(series_comic_zip_symlink)

    if year_comic_zip_symlink_timestamp < zip_file_timestamp:
        logger.debug(f'Year symlink is out of date WRT zip file: "{year_comic_zip_symlink}".')
        return False

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

        if not is_configured:
            display_ttl = ttl if ttl_info.comic_book_info.is_barks_title else f"({ttl})"
            fixes_flg = EMPTY_FLAG
            build_state_flg = NOT_CONFIGURED_FLAG
            num_pgs = -1
            page_lst = ""
            has_front = False
            num_splashes = 0
        else:
            comic_book = comics_database.get_comic_book(ttl)

            display_ttl = ttl if comic_book.is_barks_title() else f"({ttl})"
            fixes_flg = FIXES_FLAG if has_fixes(comic_book) else EMPTY_FLAG
            build_state_flg = get_build_state_flag(comic_book)
            page_lst = ", ".join(get_abbrev_jpg_page_list(comic_book)).replace(" - ", "-")
            num_pgs = get_total_num_pages(comic_book)
            if num_pgs <= 0:
                msg = f'For title "{ttl}", the page count is too small.'
                raise RuntimeError(msg)
            has_front = get_has_front(comic_book)
            num_splashes = get_num_splashes(comic_book)

        if fixes_flg not in fixes_filter:
            continue
        if build_state_flg not in built_filter:
            continue

        max_ttl_len = max(max_ttl_len, len(display_ttl))
        max_issue_ttl_len = max(max_issue_ttl_len, len(issue_ttl))

        ttl_flags[ttl] = Flags(
            display_ttl,
            fixes_flg,
            build_state_flg,
            num_pgs,
            page_lst,
            has_front,
            num_splashes,
        )

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


@app.command(help="Fantagraphics info")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    fixes: str = "",
    built: str = "",
) -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    if volumes_str and title_str:
        msg = "Options --volume and --title are mutually exclusive."
        raise typer.BadParameter(msg)

    volumes = list(intspan(volumes_str))

    comics_database = ComicsDatabase()

    fixes_filter = get_fixes_filter(fixes)
    built_filter = get_built_filter(built)
    display_volumes = not volumes or len(volumes) > 1

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

        style = "orange1" if flags.build_state_flag != BUILT_FLAG else None
        table.add_row(*row, style=style)

    console.print(table)


if __name__ == "__main__":
    app()
