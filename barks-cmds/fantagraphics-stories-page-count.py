# ruff: noqa: T201

import sys
from pathlib import Path

from barks_fantagraphics.comic_book import get_total_num_pages
from barks_fantagraphics.comics_cmd_args import CmdArgNames, CmdArgs
from loguru import logger
from loguru_config import LoguruConfig

if __name__ == "__main__":
    cmd_args = CmdArgs("Fantagraphics volume page counts", CmdArgNames.VOLUME)
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variable accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = cmd_args.get_comics_database()

    titles = cmd_args.get_titles()

    page_count = 0
    for title in titles:
        comic_book = comics_database.get_comic_book(title)
        num_pages = get_total_num_pages(comic_book)
        if num_pages <= 1:
            msg = f'For title "{title}", the page count is too small.'
            raise ValueError(msg)
        page_count += num_pages

    print(f"{len(titles)} titles, {page_count} pages")
