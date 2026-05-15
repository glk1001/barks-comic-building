from pathlib import Path

import cv2 as cv
import typer
from barks_fantagraphics.comic_book_info import BARKS_TITLE_DICT
from barks_fantagraphics.comics_consts import PNG_FILE_EXT, RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import draw_panel_bounds_on_image
from barks_fantagraphics.panel_boxes import TitlePanelBoxes, check_page_panel_boxes
from comic_utils.common_typer_options import LogLevelArg, TitleArg
from comic_utils.cv_image_utils import get_bw_image_from_alpha
from comic_utils.kivy_page_viewer import KivyPageViewer
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
    win_left: int,
    win_top: int,
) -> None:
    """Display panel-bounds overlays for ``title`` in a Kivy viewer window.

    Args:
        comics_database: The comics database used to resolve the title.
        title: The Barks title to display.
        start_page: 1-based page index to show first. Clamped to the available range.
        win_left: Window left position in pixels.
        win_top: Window top position in pixels.

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
        win_left=win_left,
        win_top=win_top,
    ).run()


app = typer.Typer()


@app.command(help="Show panel bounds for title")
def main(
    title_str: TitleArg,
    page: int = typer.Option(1, "--page", "-p", help="Page number to start on (1-based)."),
    win_left: int = typer.Option(100, "--win-left", help="Window left position in pixels."),
    win_top: int = typer.Option(100, "--win-top", help="Window top position in pixels."),
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    comics_database = ComicsDatabase()

    show_panel_bounds(comics_database, title_str, page, win_left, win_top)


if __name__ == "__main__":
    app()
