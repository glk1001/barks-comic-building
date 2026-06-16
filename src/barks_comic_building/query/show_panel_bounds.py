from pathlib import Path

import cv2 as cv
import typer
from barks_fantagraphics.barks_titles import STR_TITLE_TO_ENUM
from barks_fantagraphics.comic_book import get_page_str
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
        STR_TITLE_TO_ENUM[title]
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
    start_fanta_page: str | None = None,
) -> None:
    """Display panel-bounds overlays for ``title`` in a Kivy viewer window.

    Args:
        comics_database: The comics database used to resolve the title.
        title: The Barks title to display.
        start_fanta_page: Fanta page string (e.g. ``"202"``) to open on. If ``None`` or
            not found among the title's restorable pages, the first page is shown.

    """
    logger.info(f'Showing panel bounds for "{title}"...')

    pages = _build_page_images(comics_database, title)
    if not pages:
        logger.error(f'No restorable pages found for "{title}".')
        return

    start_page = 1
    if start_fanta_page is not None:
        fanta_pages = [fanta_page for fanta_page, _ in pages]
        if start_fanta_page in fanta_pages:
            start_page = fanta_pages.index(start_fanta_page) + 1
        else:
            logger.warning(
                f'Fanta page "{start_fanta_page}" not found in "{title}"; showing first page.'
            )

    KivyPageViewer(
        window_title=f"Panel bounds — {title}",
        pages=pages,
        start_page=start_page,
    ).run()


app = typer.Typer()


@app.command(help="Show panel bounds for a title")
def main(
    title_str: TitleArg = "",
    volume: int | None = typer.Option(
        None,
        "--volume",
        "-v",
        help="Fanta volume; use with --fanta-page to look up the title. "
        "Mutually exclusive with --title.",
    ),
    fanta_page: int | None = typer.Option(
        None,
        "--fanta-page",
        "-p",
        help="Fanta volume page to open on; use with --volume. Mutually exclusive with --title.",
    ),
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    using_volume = volume is not None or fanta_page is not None
    if title_str and using_volume:
        msg = "Options --title and --volume/--fanta-page are mutually exclusive."
        raise typer.BadParameter(msg)

    comics_database = ComicsDatabase()

    start_fanta_page: str | None = None
    if using_volume:
        if volume is None or fanta_page is None:
            msg = "Options --volume and --fanta-page must be given together."
            raise typer.BadParameter(msg)
        start_fanta_page = get_page_str(fanta_page)
        title_str, _ = get_title_from_volume_page(comics_database, volume, start_fanta_page)
        if not title_str:
            msg = f'No title found for volume {volume}, page "{start_fanta_page}".'
            raise typer.BadParameter(msg)
        logger.info(f'Resolved volume {volume}, page "{start_fanta_page}" -> title="{title_str}".')

    if not title_str:
        msg = "Must pass --title, or --volume with --fanta-page."
        raise typer.BadParameter(msg)

    show_panel_bounds(comics_database, title_str, start_fanta_page)


if __name__ == "__main__":
    app()
