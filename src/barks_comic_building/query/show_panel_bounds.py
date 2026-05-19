from pathlib import Path

import cv2 as cv
import typer
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comic_book_info import BARKS_TITLE_DICT
from barks_fantagraphics.comics_consts import PNG_FILE_EXT, RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import (
    draw_panel_bounds_on_image,
    get_title_from_volume_page,
)
from barks_fantagraphics.panel_boxes import TitlePanelBoxes, check_page_panel_boxes
from barks_kivy_ui.page_viewer import KivyPageViewer
from comic_utils.common_typer_options import LogLevelArg, TitleArg
from comic_utils.cv_image_utils import get_bw_image_from_alpha, validate_page_bw_image
from loguru import logger
from PIL import Image

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "span"


def _build_page_images(
    comics_database: ComicsDatabase, title: str
) -> list[tuple[str, Image.Image]]:
    comic = comics_database.get_comic_book(title)
    svg_files = comic.get_srce_restored_svg_story_files(RESTORABLE_PAGE_TYPES)
    title_pages_panel_boxes = TitlePanelBoxes(comics_database).get_page_panel_boxes(
        BARKS_TITLE_DICT[title]
    )

    pages: list[tuple[str, Image.Image]] = []
    for svg_file in svg_files:
        fanta_page = svg_file.stem

        png_file = Path(str(svg_file) + PNG_FILE_EXT)
        if not png_file.is_file():
            msg = f'Page PNG not found: "{png_file}".'
            raise FileNotFoundError(msg)
        bw_image = get_bw_image_from_alpha(png_file)
        validate_page_bw_image(bw_image, png_file)
        pil_image = Image.fromarray(cv.merge([bw_image, bw_image, bw_image])).convert("RGBA")

        page_panel_boxes = title_pages_panel_boxes.pages[fanta_page]
        check_page_panel_boxes(pil_image.size, page_panel_boxes)
        draw_panel_bounds_on_image(pil_image, page_panel_boxes)

        pages.append((fanta_page, pil_image))

    return pages


def show_panel_bounds(
    comics_database: ComicsDatabase,
    title: str,
    start_page: int,
) -> None:
    """Display panel-bounds overlays for ``title`` in a Kivy viewer window.

    Args:
        comics_database: The comics database used to resolve the title.
        title: The Barks title to display.
        start_page: 1-based page index to show first. Clamped to the available range.

    """
    logger.info(f'Showing panel bounds for "{title}"...')

    pages = _build_page_images(comics_database, title)
    if not pages:
        logger.error(f'No restorable pages found for "{title}".')
        return

    KivyPageViewer(
        window_title=f"Panel bounds — {title}",
        pages=pages,
        start_page=start_page,
    ).run()


app = typer.Typer()


@app.command(help="Show panel bounds for title")
def main(
    title_str: TitleArg = "",
    volume: int | None = typer.Option(
        None,
        "--volume",
        "-v",
        help="Fanta volume; use with --page to look up the title. Mutually exclusive with --title.",
    ),
    page: int = typer.Option(1, "--page", "-p", help="Page number to start on (1-based)."),
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    if title_str and volume is not None:
        msg = "Options --title and --volume are mutually exclusive."
        raise typer.BadParameter(msg)

    comics_database = ComicsDatabase()

    if volume is not None:
        page_str = get_page_str(page)
        title_str, page = get_title_from_volume_page(comics_database, volume, page_str)
        if not title_str:
            msg = f'No title found for volume {volume}, page "{page_str}".'
            raise typer.BadParameter(msg)
        logger.info(
            f'Resolved volume {volume}, page "{page_str}" -> title="{title_str}", page={page}.'
        )

    if not title_str:
        msg = "Must pass --title, or --volume with --page."
        raise typer.BadParameter(msg)

    show_panel_bounds(comics_database, title_str, page)


if __name__ == "__main__":
    app()
