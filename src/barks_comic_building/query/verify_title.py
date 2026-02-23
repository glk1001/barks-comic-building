# ruff: noqa: T201

from pathlib import Path

import typer
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_display_title, get_issue_title
from comic_utils.common_typer_options import LogLevelArg, TitleArg
from loguru_config import LoguruConfig

import barks_comic_building.log_setup as _log_setup

APP_LOGGING_NAME = "vttl"

_RESOURCES = Path(__file__).parent.parent / "resources"

app = typer.Typer()


@app.command(help="Verify a title or issue number")
def main(
    title: TitleArg,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    _log_setup.log_level = log_level_str
    _log_setup.log_filename = "barks-cmds.log"
    _log_setup.APP_LOGGING_NAME = APP_LOGGING_NAME
    LoguruConfig.load(_RESOURCES / "log-config.yaml")

    comics_database = ComicsDatabase()

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
            display_title = get_display_title(comics_database, title)
            issue_title = get_issue_title(comics_database, title)
            fanta_vol = comics_database.get_fanta_volume(title)
            print(f'This is a valid title: "{display_title}" [{issue_title}], {fanta_vol}.')
        elif close:
            print(f'"{title}" is not a valid title. Did you mean: "{close}".')
        else:
            print(f'"{title}" is not a valid title. Cannot find anything close to this.')


if __name__ == "__main__":
    app()
