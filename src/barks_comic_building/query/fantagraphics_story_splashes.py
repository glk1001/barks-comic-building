# ruff: noqa: T201

import json
from pathlib import Path

import typer
from barks_fantagraphics import panel_bounding
from barks_fantagraphics.comic_book import ComicBook, get_page_str
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_titles
from barks_fantagraphics.fanta_comics_info import get_fanta_volume_str
from barks_fantagraphics.pages import PageType, get_sorted_srce_and_dest_pages
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comic_utils.panel_segmentation import BIG_NUM, get_kumiko_panel_bound
from intspan import intspan
from loguru_config import LoguruConfig

import barks_comic_building.log_setup as _log_setup

APP_LOGGING_NAME = "spla"

_RESOURCES = Path(__file__).parent.parent / "resources"

MAX_NUM_PANELS_FOR_SPLASH = 5


def get_story_splashes(comic: ComicBook) -> list[str]:
    srce_and_dest_pages = get_sorted_srce_and_dest_pages(comic, get_full_paths=True)

    splashes = []
    for srce_page, dest_page in zip(
        srce_and_dest_pages.srce_pages, srce_and_dest_pages.dest_pages, strict=True
    ):
        if srce_page.page_type is not PageType.BODY:
            continue
        if dest_page.page_num == 1:  # Don't count large panels on first page
            continue

        srce_page_str = get_page_str(srce_page.page_num)

        panels_info_file = comic.get_srce_panel_segments_file(srce_page_str)
        if not panels_info_file.is_file():
            msg = f'Could not find panels segments info file "{panels_info_file}".'
            raise FileNotFoundError(msg)

        with panels_info_file.open() as f:
            panels = json.load(f)["panels"]

        if has_splash_page(panels):
            splashes.append(srce_page_str)

    return splashes


MIN_MAX_MARGIN = 200


def has_splash_page(panels: list[tuple[int, int, int, int]]) -> bool:
    if len(panels) > MAX_NUM_PANELS_FOR_SPLASH:
        return False

    max_width = -1
    max_height = -1
    min_width = BIG_NUM
    min_height = BIG_NUM
    for _index, panel in enumerate(panels):
        bound = get_kumiko_panel_bound(panel)

        min_width = min(min_width, bound.width)
        min_height = min(min_height, bound.height)
        max_width = max(max_width, bound.width)
        max_height = max(max_height, bound.height)

    return (
        abs(max_width - min_width) > MIN_MAX_MARGIN
        and abs(max_height - min_height) > MIN_MAX_MARGIN
    )


app = typer.Typer()


@app.command(help="Fantagraphics volumes splash pages")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    _log_setup.log_level = log_level_str
    _log_setup.log_filename = "barks-cmds.log"
    _log_setup.APP_LOGGING_NAME = APP_LOGGING_NAME
    LoguruConfig.load(_RESOURCES / "log-config.yaml")

    if volumes_str and title_str:
        msg = "Options --volume and --title are mutually exclusive."
        raise typer.BadParameter(msg)

    volumes = list(intspan(volumes_str))
    comics_database = ComicsDatabase()
    panel_bounding.warn_on_panels_bbox_height_less_than_av = False
    titles = get_titles(comics_database, volumes, title_str)

    splashes_dict = {}
    max_title_len = 0
    for title in titles:
        comic_book = comics_database.get_comic_book(title)

        story_splashes = get_story_splashes(comic_book)
        if not story_splashes:
            continue

        title_with_issue_num = comic_book.get_title_with_issue_num()
        max_title_len = max(max_title_len, len(title_with_issue_num))

        volume = comic_book.get_fanta_volume()

        splashes_dict[title_with_issue_num] = (volume, story_splashes)

    for title, (volume, story_splashes) in splashes_dict.items():
        volume_str = get_fanta_volume_str(volume)
        splashes_str = ", ".join(story_splashes)

        print(f'"{title:<{max_title_len}}", {volume_str}, Splashes: {splashes_str}')


if __name__ == "__main__":
    app()
