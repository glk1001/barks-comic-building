from pathlib import Path

import cv2 as cv
import typer
from barks_fantagraphics.barks_titles import ENUM_TO_STR_TITLE, STR_TITLE_TO_ENUM, Titles
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comic_book_info import (
    ONE_PAGERS,
    get_one_pager_fanta_vol_and_page,
)
from barks_fantagraphics.comics_consts import PNG_FILE_EXT, RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import (
    draw_panel_bounds_on_image,
    get_title_from_volume_page,
)
from barks_fantagraphics.panel_boxes import (
    PagePanelBoxes,
    TitlePanelBoxes,
    check_page_panel_boxes,
)
from barks_kivy_ui.page_viewer import KivyPageViewer
from comic_utils.comic_consts import JSON_FILE_EXT, SVG_FILE_EXT
from comic_utils.common_typer_options import LogLevelArg, TitleArg
from comic_utils.cv_image_utils import get_bw_image_from_alpha, validate_page_bw_image
from loguru import logger
from PIL import Image

from barks_comic_building.build.stage_one_pagers import get_staged_links_by_title
from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "span"


def _draw_page(png_file: Path, page_panel_boxes: PagePanelBoxes) -> Image.Image:
    """Return one restored page with its panel bounds drawn on.

    Args:
        png_file: The restored svg's png rendering.
        page_panel_boxes: That page's panels, from its segments file.

    Returns:
        The page image, ready for the viewer.

    Raises:
        FileNotFoundError: If the page png is not there.

    """
    if not png_file.is_file():
        msg = f'Page PNG not found: "{png_file}".'
        raise FileNotFoundError(msg)

    bw_image = get_bw_image_from_alpha(png_file)
    validate_page_bw_image(bw_image, png_file)
    pil_image = Image.fromarray(cv.merge([bw_image, bw_image, bw_image])).convert("RGBA")

    check_page_panel_boxes(pil_image.size, page_panel_boxes)
    draw_panel_bounds_on_image(pil_image, page_panel_boxes)

    return pil_image


def page_home_file(link: Path, source: Path) -> Path:
    """Return the page's own file: the volume's when it has one, else the collection's.

    The two read the same bytes whenever the slot is a link, so this is about which path
    a message names. It should be the one the work is done in - the volume's - because
    that is where the `bounded` override goes and where `barks-batch-panel-bounds` is
    re-run. A one-pager whose volume never restored it has no source at all, and then the
    collection really is its home.

    Args:
        link: The collection's staged slot.
        source: The file in the one-pager's own volume, which may not exist.

    Returns:
        The path to read the page from.

    """
    return source if source.is_file() else link


def one_pager_where(title: Titles) -> str:
    """Return where a one-pager's page lives, for the window title - "Vol 20, page 095"."""
    volume, page = get_one_pager_fanta_vol_and_page(title)
    if volume is None or page is None:
        return "no authored location"

    return f"Vol {volume}, page {get_page_str(page)}"


def one_pager_page_images(
    comics_database: ComicsDatabase, title: Titles
) -> list[tuple[str, Image.Image]]:
    """Return the one page of a one-pager, labelled by the volume it really lives in.

    A one-pager has no `.ini` of its own - it is a member of the `All One-Pagers`
    collection - so `get_comic_book` cannot open it and neither can
    `TitlePanelBoxes.get_page_panel_boxes`, which is where this used to raise
    `TitleNotFoundError` with a "did you mean" suggestion naming an unrelated story.

    The collection is where the page is reachable, and the stager is asked for the paths
    rather than the collection page number being worked out again here - it owns that
    numbering. Going to the home volume's trees directly would look simpler and is wrong:
    a one-pager whose volume never restored it has its only restored png and segments
    file *in* the collection, written there by a pipeline run over the collection itself.
    `Art Appreciation` is in that state, with nothing at all under volume 28.

    The page is labelled with its volume page rather than its collection page, because
    that is the page the `bounded` override and the `barks-batch-panel-bounds` re-run are
    both keyed by - the collection page number is only how the file was reached.

    Args:
        comics_database: The comics database supplying the volume directory paths.
        title: The one-pager to show.

    Returns:
        The single page and its label, or empty if the one-pager has no authored location.

    """
    links = get_staged_links_by_title(comics_database).get(title)
    if not links:
        logger.error(
            f'"{ENUM_TO_STR_TITLE[title]}" is a one-pager with no authored location,'
            f" so it is not staged into the collection and has no page to show."
        )
        return []

    png_file = next(
        page_home_file(link, source)
        for link, source in links
        if link.name.endswith(SVG_FILE_EXT + PNG_FILE_EXT)
    )
    segments_file = next(
        page_home_file(link, source) for link, source in links if link.suffix == JSON_FILE_EXT
    )

    _volume, volume_page = get_one_pager_fanta_vol_and_page(title)
    label = get_page_str(volume_page) if volume_page is not None else png_file.stem

    page_panel_boxes = TitlePanelBoxes(comics_database).get_panel_boxes(segments_file, label)

    return [(label, _draw_page(png_file, page_panel_boxes))]


def _build_page_images(
    comics_database: ComicsDatabase, title: str
) -> list[tuple[str, Image.Image]]:
    comic = comics_database.get_comic_book(title)
    svg_files = comic.get_srce_restored_svg_story_files(RESTORABLE_PAGE_TYPES)
    title_pages_panel_boxes = TitlePanelBoxes(comics_database).get_page_panel_boxes(
        STR_TITLE_TO_ENUM[title]
    )

    return [
        (
            svg_file.stem,
            _draw_page(
                Path(str(svg_file) + PNG_FILE_EXT), title_pages_panel_boxes.pages[svg_file.stem]
            ),
        )
        for svg_file in svg_files
    ]


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
            not found among the title's restorable pages, the first page is shown. A
            one-pager's single page is labelled by its volume page, so the page asked for
            here is the page shown.

    """
    logger.info(f'Showing panel bounds for "{title}"...')

    # A one-pager is not a story the database holds, so it cannot be opened as a comic
    # book at all - see `one_pager_page_images` for where its one page is reachable.
    title_enum = STR_TITLE_TO_ENUM[title]
    window_title = f"Panel bounds — {title}"
    if title_enum in ONE_PAGERS:
        pages = one_pager_page_images(comics_database, title_enum)
        window_title = f"{window_title} ({one_pager_where(title_enum)})"
    else:
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
        window_title=window_title,
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
