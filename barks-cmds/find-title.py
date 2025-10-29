# ruff: noqa: T201

import sys
from pathlib import Path

from barks_fantagraphics.barks_titles import BARKS_TITLE_INFO
from barks_fantagraphics.comics_cmd_args import CmdArgs, ExtraArg
from barks_fantagraphics.title_search import BarksTitleSearch
from loguru import logger
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "fttl"

EXTRA_ARGS: list[ExtraArg] = [
    ExtraArg("--prefix", action="store", type=str, default=""),
    ExtraArg("--word", action="store", type=str, default=""),
    ExtraArg("--sort", action="store_true", type=bool, default=False),
]

if __name__ == "__main__":
    cmd_args = CmdArgs("Find title", extra_args=EXTRA_ARGS)
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variable accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = cmd_args.get_comics_database()
    prefix = cmd_args.get_extra_arg("--prefix")
    word = cmd_args.get_extra_arg("--word")

    title_search = BarksTitleSearch()

    titles = []

    if prefix:
        titles.append(title_search.get_titles_matching_prefix(prefix))
    if word:
        titles.append(title_search.get_titles_containing(word))

    if not titles:
        print("No titles found.")
    else:
        titles = list(set(titles))  # get rid of duplicate titles
        title_info_list = [BARKS_TITLE_INFO[t] for t in titles]

        if cmd_args.get_extra_arg("--sort"):
            title_info_list = sorted(title_info_list, key=lambda x: x.get_title_str())

        for info in title_info_list:
            print(info.get_display_title())
