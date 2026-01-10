# ruff: noqa: T201

import json
from dataclasses import dataclass
from pathlib import Path

import typer
from barks_fantagraphics import panel_bounding
from barks_fantagraphics.comic_book import ComicBook
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_titles
from barks_fantagraphics.page_classes import ComicDimensions
from barks_fantagraphics.pages import PageType, get_sorted_srce_and_dest_pages
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from intspan import intspan
from loguru_config import LoguruConfig
from PIL import Image

APP_LOGGING_NAME = "sdim"

app = typer.Typer()
log_level = ""


@dataclass
class Dimensions:
    srce_dims: ComicDimensions
    front_width: int
    front_height: int


def get_story_dimensions(comic: ComicBook) -> Dimensions:
    srce_and_dest_pages = get_sorted_srce_and_dest_pages(comic, get_full_paths=True)

    front_width = -1
    front_height = -1
    front_page = srce_and_dest_pages.srce_pages[0]
    if front_page.page_type == PageType.FRONT:
        image = Image.open(front_page.page_filename, "r")
        front_width = image.width
        front_height = image.height

    srce_dims = ComicDimensions()
    metadata_file = comic.get_dest_dir() / "comic-metadata.json"
    with metadata_file.open() as f:
        comic_metadata = json.load(f)
        srce_dims.min_panels_bbox_width = comic_metadata["srce_min_panels_bbox_width"]
        srce_dims.max_panels_bbox_width = comic_metadata["srce_max_panels_bbox_width"]
        srce_dims.min_panels_bbox_height = comic_metadata["srce_min_panels_bbox_height"]
        srce_dims.max_panels_bbox_height = comic_metadata["srce_max_panels_bbox_height"]
        srce_dims.av_panels_bbox_width = comic_metadata["srce_av_panels_bbox_width"]
        srce_dims.av_panels_bbox_height = comic_metadata["srce_av_panels_bbox_height"]

    return Dimensions(srce_dims, front_width, front_height)


@app.command(help="Fantagraphics volumes story panel dimensions")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
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
    panel_bounding.warn_on_panels_bbox_height_less_than_av = False
    titles = get_titles(comics_database, volumes, title_str)

    dimensions_dict = {}
    max_title_len = 0
    for title in titles:
        comic_book = comics_database.get_comic_book(title)

        story_dims = get_story_dimensions(comic_book)

        title_with_issue_num = comic_book.get_title_with_issue_num()
        max_title_len = max(max_title_len, len(title_with_issue_num))

        dimensions_dict[title_with_issue_num] = story_dims

    for title, story_dims in dimensions_dict.items():
        title_str = title + ":"

        box_dims = story_dims.srce_dims
        bboxes_str = (
            f"{box_dims.min_panels_bbox_width:4},{box_dims.max_panels_bbox_width}"
            f" {box_dims.min_panels_bbox_height:4},{box_dims.max_panels_bbox_height}"
            f" {box_dims.av_panels_bbox_width:4},{box_dims.av_panels_bbox_height}"
        )

        front_str = (
            ""
            if story_dims.front_width == -1
            else f"Front: {story_dims.front_width:4} x {story_dims.front_height:4}"
        )

        print(f"{title_str:<{max_title_len + 1}} BBoxes: {bboxes_str}  {front_str}")


if __name__ == "__main__":
    app()
