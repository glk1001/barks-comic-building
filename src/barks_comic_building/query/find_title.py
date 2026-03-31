# ruff: noqa: T201


import typer
from barks_fantagraphics.barks_titles import BARKS_TITLE_INFO
from barks_fantagraphics.title_search import BarksTitleSearch
from comic_utils.common_typer_options import LogLevelArg

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "fttl"

app = typer.Typer()


@app.command(help="Find a title from prefix or word")
def main(
    prefix: str = "",
    word: str = "",
    sort: bool = False,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    title_search = BarksTitleSearch()

    titles = []

    if prefix:
        titles.extend(title_search.get_titles_matching_prefix(prefix))
    if word:
        titles.extend(title_search.get_titles_containing(word))

    if not titles:
        print("No titles found.")
    else:
        titles = list(set(titles))  # get rid of duplicate titles
        title_info_list = [BARKS_TITLE_INFO[t] for t in titles]

        if sort:
            title_info_list = sorted(title_info_list, key=lambda x: x.get_title_str())

        for info in title_info_list:
            print(info.get_display_title())


if __name__ == "__main__":
    app()
