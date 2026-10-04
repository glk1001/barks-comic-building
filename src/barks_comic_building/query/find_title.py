# ruff: noqa: T201

from typing import Annotated

import typer
from barks_fantagraphics.comic_book_info import BARKS_TITLE_INFO
from barks_fantagraphics.title_search import BarksTitleSearch
from comic_utils.common_typer_options import LogLevelArg

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "fttl"

app = typer.Typer()


@app.command(help="Find titles as the reader's title search does: by words, issue or 'covers'.")
def main(
    text: Annotated[
        str, typer.Argument(help='What to look for: "gold fleece", "CS 104" or "covers".')
    ],
    sort: Annotated[bool, typer.Option(help="List alphabetically, not chronologically.")] = False,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    titles = BarksTitleSearch().find_titles(text)

    if not titles:
        print("No titles found.")
        return

    title_info_list = [BARKS_TITLE_INFO[t] for t in titles]
    if sort:
        title_info_list = sorted(title_info_list, key=lambda x: x.get_title_str())

    for info in title_info_list:
        print(info.get_display_title())


if __name__ == "__main__":
    app()
