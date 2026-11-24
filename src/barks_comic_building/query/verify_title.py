"""Say whether a string is a Barks title or an issue, and where it is."""
# ruff: noqa: T201

import difflib

import typer
from barks_fantagraphics.barks_titles import STR_TITLE_TO_ENUM, Titles
from barks_fantagraphics.comic_book_info import BARKS_TITLE_INFO, COVERS_SET, ONE_PAGERS
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_display_title, get_issue_title
from barks_fantagraphics.fanta_comics_info import ALL_FANTA_COMIC_BOOK_INFO
from comic_utils.common_typer_options import LogLevelArg, TitleArg

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "vttl"

# The cutoff `ComicsDatabase.is_story_title` uses for its own suggestion.
_CLOSE_MATCH_CUTOFF = 0.3

app = typer.Typer()


def get_title_kind(title: Titles) -> str:
    """Say what kind of title one with no ini file of its own is."""
    if title in ONE_PAGERS:
        return "a one-pager"
    if title in COVERS_SET:
        return "a cover"
    return "a story with no ini file yet"


def describe_title_without_ini(title_str: str) -> str:
    """Describe a real title the comics database cannot open.

    One-pagers and covers are pages of the two collections, and a story not yet worked
    on has no ini file, so the database knows none of them - but each is a title all the
    same, with an issue and usually a volume.

    Args:
        title_str: A title in `STR_TITLE_TO_ENUM`.

    Returns:
        The line to print for it.

    """
    title = STR_TITLE_TO_ENUM[title_str]
    info = BARKS_TITLE_INFO[title]
    fanta_info = ALL_FANTA_COMIC_BOOK_INFO.get(title)
    fanta_vol = fanta_info.fantagraphics_volume if fanta_info else "no Fantagraphics volume"

    return (
        f'This is a valid title: "{info.get_display_title()}" [{info.get_short_issue_title()}],'
        f" {fanta_vol} ({get_title_kind(title)})."
    )


def get_story_title_verdict(comics_database: ComicsDatabase, title: str) -> str:
    """Say whether a string is a title, and if not, which title it is closest to.

    Validity is decided by the title list, not by the database: the database only knows
    the titles that have an ini file, and asking it alone called every one-pager, cover
    and unconfigured story invalid - "If the Hat Fits" was "not a valid title. Did you
    mean: In the Swim".

    Args:
        comics_database: The database to look a configured title up in.
        title: The string to check.

    Returns:
        The line to print for it.

    """
    is_configured, _close = comics_database.is_story_title(title)
    if is_configured:
        display_title = get_display_title(comics_database, title)
        issue_title = get_issue_title(comics_database, title)
        fanta_vol = comics_database.get_fanta_volume(title)
        return f'This is a valid title: "{display_title}" [{issue_title}], {fanta_vol}.'

    if title in STR_TITLE_TO_ENUM:
        return describe_title_without_ini(title)

    close = difflib.get_close_matches(title, list(STR_TITLE_TO_ENUM), 1, _CLOSE_MATCH_CUTOFF)
    if close:
        return f'"{title}" is not a valid title. Did you mean: "{close[0]}".'

    return f'"{title}" is not a valid title. Cannot find anything close to this.'


@app.command(help="Verify a title or issue number")
def main(
    title: TitleArg,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    comics_database = ComicsDatabase()

    found, titles, close = comics_database.get_story_title_from_issue(title)
    if found:
        titles_str = ", ".join([f'"{t}"' for t in titles])
        fanta_vol = comics_database.get_fanta_volume(titles[0])
        print(f'This is an issue title: "{title}" -> title: {titles_str}, {fanta_vol}')
    elif close and title not in STR_TITLE_TO_ENUM:
        print(f'"{title}" is not a valid issue title. Did you mean: "{close}".')
    else:
        print(get_story_title_verdict(comics_database, title))


if __name__ == "__main__":
    app()
