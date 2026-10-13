# ruff: noqa: T201
"""Draw every story's title page, small, onto contact sheets, to look over at a glance.

A change to the title page shows on every story's page at once here: a title crowding
the page's edges, a name broken badly, a colour that fades. The pages are drawn as the
reader draws them, each around its story's own inset, so the comic library must be in
place. They are in chronological order, labelled with each story's number and title.
"""

from itertools import batched
from pathlib import Path
from typing import Annotated

import typer
from barks_build_comic_images.build_comic_images import ComicBookImageBuilder
from barks_build_comic_images.image_io import open_image_for_reading
from barks_fantagraphics.barks_titles import ENUM_TO_STR_TITLE
from barks_fantagraphics.comic_book_info import NON_COMIC_TITLES, SYNTHETIC_TITLES
from barks_fantagraphics.comics_consts import INTRO_PUB_TEXT_FONT_FILE, PageType
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.page_classes import CleanPage
from barks_fantagraphics.pages import EMPTY_IMAGE_FILEPATH
from comic_utils.common_typer_options import LogLevelArg
from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "tpsh"

THUMB_WIDTH = 300
LABEL_HEIGHT = 34
LABEL_FONT_SIZE = 18
GAP = 12
BACKGROUND_COLOR = (60, 60, 60)
LABEL_COLOR = (255, 255, 255)
# A page that could not be drawn is left as a cell of this colour, still labelled.
NOT_DRAWN_COLOR = (150, 40, 40)

# The essays and the collections have no title page.
_NO_TITLE_PAGE = {ENUM_TO_STR_TITLE[title] for title in [*NON_COMIC_TITLES, *SYNTHETIC_TITLES]}


def get_thumb_size(page_size: tuple[int, int]) -> tuple[int, int]:
    """Return the size of a page's thumbnail: ``THUMB_WIDTH`` wide, in the page's shape.

    Args:
        page_size: The full page's width and height.

    Returns:
        The thumbnail's width and height.

    """
    width, height = page_size
    return THUMB_WIDTH, round(height * THUMB_WIDTH / width)


def fit_label(label: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    """Return a label short enough to fit a width, cut short with an ellipsis if need be.

    Args:
        label: The label.
        font: The label's font.
        width: The room for it.

    Returns:
        The label, or as much of it as fits followed by "…".

    """
    if font.getlength(label) <= width:
        return label
    while label and font.getlength(f"{label}…") > width:
        label = label[:-1]
    return f"{label.rstrip()}…"


def make_sheet(
    thumbs: list[tuple[str, Image.Image]],
    columns: int,
    thumb_size: tuple[int, int],
) -> Image.Image:
    """Lay thumbnails out in rows, each with its label under it.

    Args:
        thumbs: Each thumbnail with its label, in reading order.
        columns: How many thumbnails across.
        thumb_size: Every thumbnail's width and height.

    Returns:
        The sheet.

    """
    thumb_width, thumb_height = thumb_size
    rows = -(-len(thumbs) // columns)
    cell_width = thumb_width + GAP
    cell_height = thumb_height + LABEL_HEIGHT + GAP
    sheet = Image.new(
        "RGB", (GAP + (columns * cell_width), GAP + (rows * cell_height)), BACKGROUND_COLOR
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(INTRO_PUB_TEXT_FONT_FILE, LABEL_FONT_SIZE)

    for i, (label, thumb) in enumerate(thumbs):
        left = GAP + ((i % columns) * cell_width)
        top = GAP + ((i // columns) * cell_height)
        sheet.paste(thumb, (left, top))
        draw.text(
            (left + (thumb_width / 2), top + thumb_height + (LABEL_HEIGHT / 2)),
            fit_label(label, font, thumb_width),
            fill=LABEL_COLOR,
            font=font,
            anchor="mm",
        )

    return sheet


def _get_title_page(builder: ComicBookImageBuilder, empty_page: Image.Image) -> Image.Image:
    title_page = CleanPage("title", PageType.TITLE)
    return builder.get_dest_page_image(empty_page, title_page, title_page)


app = typer.Typer()


@app.command(help="Draw every story's title page onto contact sheets")
def main(
    out_dir: Annotated[Path, typer.Argument(help="Where to write the sheets.")],
    columns: Annotated[int, typer.Option(help="Title pages across a sheet.")] = 8,
    rows: Annotated[int, typer.Option(help="Title pages down a sheet.")] = 6,
    # The builder logs every page it draws at INFO, burying the progress lines.
    log_level_str: LogLevelArg = "WARNING",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    comics_database = ComicsDatabase()
    comics = sorted(
        (
            comics_database.get_comic_book(title)
            for title in comics_database.get_all_story_titles()
            if title not in _NO_TITLE_PAGE
        ),
        key=lambda comic: comic.chronological_number,
    )
    empty_page = open_image_for_reading(EMPTY_IMAGE_FILEPATH)
    thumb_size = get_thumb_size(empty_page.size)
    out_dir.mkdir(parents=True, exist_ok=True)

    not_drawn = []
    sheets = batched(comics, columns * rows, strict=False)  # the last sheet may be short
    for sheet_num, sheet_comics in enumerate(sheets, start=1):
        thumbs = []
        for comic in sheet_comics:
            label = f"{comic.chronological_number:03} {comic.get_ini_title()}"
            try:
                page = _get_title_page(
                    ComicBookImageBuilder(comic, EMPTY_IMAGE_FILEPATH), empty_page
                )
                thumb = page.resize(thumb_size, Image.Resampling.LANCZOS)
            except (FileNotFoundError, ValueError) as e:
                logger.error(f'Could not draw the title page of "{label}": {e}')
                not_drawn.append(f"{label}: {e}")
                thumb = Image.new("RGB", thumb_size, NOT_DRAWN_COLOR)
            thumbs.append((label, thumb))

        sheet_file = out_dir / f"title-pages-{sheet_num:02}.jpg"
        make_sheet(thumbs, columns, thumb_size).save(sheet_file, quality=90)
        print(f'Wrote "{sheet_file}" ({len(thumbs)} title pages).')

    print(f"Drew {len(comics) - len(not_drawn)} of {len(comics)} title pages.")
    for line in not_drawn:
        print(f"  Not drawn: {line}")


if __name__ == "__main__":
    app()
