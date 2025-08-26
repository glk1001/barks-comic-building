# ruff: noqa: T201

import sys
from pathlib import Path

from barks_fantagraphics.barks_titles import get_safe_title
from barks_fantagraphics.comics_cmd_args import CmdArgNames, CmdArgs
from loguru import logger
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "vttl"


def get_display_title(ttl: str) -> str:
    title_is_configured, _ = comics_database.is_story_title(ttl)
    if not title_is_configured:
        disp_title = ttl
    else:
        fanta_info = comics_database.get_fanta_comic_book_info(ttl)
        disp_title = ttl if fanta_info.comic_book_info.is_barks_title else f"({ttl})"

    return disp_title


def get_issue_title(ttl: str) -> str:
    title_is_configured, _ = comics_database.is_story_title(ttl)
    if not title_is_configured:
        comic_issue_title = ttl
    else:
        comic = comics_database.get_comic_book(ttl)
        comic_issue_title = get_safe_title(comic.get_comic_issue_title())

    return comic_issue_title


if __name__ == "__main__":
    cmd_args = CmdArgs("Verify title", CmdArgNames.TITLE)
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variable accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = cmd_args.get_comics_database()
    title = cmd_args.get_title()

    found, titles, close = comics_database.get_story_title_from_issue(title)
    if found:
        titles_str = ", ".join([f'"{t}"' for t in titles])
        fanta_vol = comics_database.get_fanta_volume(titles[0])
        print(f'This is an issue title: "{title}" -> title: {titles_str}, {fanta_vol}')
    elif close:
        print(f'"{title}" is not a valid issue title. Did you mean: "{close}".')
    else:
        found, close = comics_database.is_story_title(title)
        if found:
            display_title = get_display_title(title)
            issue_title = get_issue_title(title)
            fanta_vol = comics_database.get_fanta_volume(title)
            print(f'This is a valid title: "{display_title}" [{issue_title}], {fanta_vol}.')
        elif close:
            print(f'"{title}" is not a valid title. Did you mean: "{close}".')
        else:
            print(f'"{title}" is not a valid title. Cannot find anything close to this.')
