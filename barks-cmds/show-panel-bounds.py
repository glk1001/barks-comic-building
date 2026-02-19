from pathlib import Path

import cv2 as cv
import typer
from barks_fantagraphics.barks_titles import BARKS_TITLE_DICT
from barks_fantagraphics.comics_consts import PNG_FILE_EXT, RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import draw_panel_bounds_on_image
from barks_fantagraphics.panel_boxes import TitlePanelBoxes, check_page_panel_boxes
from comic_utils.common_typer_options import LogLevelArg, TitleArg
from comic_utils.cv_image_utils import get_bw_image_from_alpha
from loguru import logger
from loguru_config import LoguruConfig
from PIL import Image

APP_LOGGING_NAME = "span"


def show_panel_bounds(comics_database: ComicsDatabase, title: str, out_dir: Path) -> None:
    out_dir /= title

    logger.info(f'Generating panel bounds images for "{title}" to directory "{out_dir}"...')

    out_dir.mkdir(parents=True, exist_ok=True)
    comic = comics_database.get_comic_book(title)
    svg_files = comic.get_srce_restored_svg_story_files(RESTORABLE_PAGE_TYPES)
    title_pages_panel_boxes = TitlePanelBoxes(comics_database).get_page_panel_boxes(
        BARKS_TITLE_DICT[title]
    )

    for svg_file in svg_files:
        fanta_page = svg_file.stem

        png_file = Path(str(svg_file) + PNG_FILE_EXT)
        bounds_img_file = out_dir / (fanta_page + "-with-bounds.png")
        bw_image = get_bw_image_from_alpha(png_file)
        pil_image = Image.fromarray(cv.merge([bw_image, bw_image, bw_image])).convert("RGBA")

        page_panel_boxes = title_pages_panel_boxes.pages[fanta_page]
        check_page_panel_boxes(pil_image.size, page_panel_boxes)
        draw_panel_bounds_on_image(pil_image, page_panel_boxes)

        pil_image.save(bounds_img_file)

    logger.info(f'Finished generating panel bounds images for "{title}" to directory "{out_dir}".')


app = typer.Typer()
log_level = ""


@app.command(help="Show panel bounds for title")
def main(
    title_str: TitleArg,
    output_dir: Path,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = ComicsDatabase()

    show_panel_bounds(comics_database, title_str, output_dir)


if __name__ == "__main__":
    app()
