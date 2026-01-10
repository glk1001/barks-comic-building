import json
from pathlib import Path

import cv2 as cv
import typer
from barks_fantagraphics.comics_consts import PNG_FILE_EXT, RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.common_typer_options import LogLevelArg, TitleArg
from comic_utils.cv_image_utils import get_bw_image_from_alpha
from comic_utils.panel_segmentation import get_min_max_panel_values
from loguru import logger
from loguru_config import LoguruConfig
from PIL import Image, ImageDraw

APP_LOGGING_NAME = "span"

app = typer.Typer()
log_level = ""


def show_panel_bounds(comics_database: ComicsDatabase, title: str, out_dir: Path) -> None:
    out_dir /= title

    logger.info(f'Generating panel bounds images for "{title}" to directory "{out_dir}"...')

    out_dir.mkdir(parents=True, exist_ok=True)
    comic = comics_database.get_comic_book(title)
    svg_files = comic.get_srce_restored_svg_story_files(RESTORABLE_PAGE_TYPES)
    panel_segments_files = comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES)

    for svg_file, panel_segments_file in zip(svg_files, panel_segments_files, strict=True):
        png_file = Path(str(svg_file) + PNG_FILE_EXT)
        bounds_img_file = out_dir / (Path(svg_file).stem + "-with-bounds.png")
        if not write_bounds_to_image_file(png_file, panel_segments_file, bounds_img_file):
            msg = "There were process errors."
            raise RuntimeError(msg)

    logger.info(f'Finished generating panel bounds images for "{title}" to directory "{out_dir}".')


def write_bounds_to_image_file(
    png_file: Path, panel_segments_file: Path, bounds_img_file: Path
) -> bool:
    logger.info(f'Writing bounds for image "{get_abbrev_path(png_file)}"...')

    if not png_file.is_file():
        logger.error(f'Could not find image file "{png_file}".')
        return False
    if not panel_segments_file.is_file():
        logger.error(f'Could not find panel segments file "{panel_segments_file}".')
        return False
    if bounds_img_file.is_file():
        logger.info(f'Found existing image bounds file - skipping: "{bounds_img_file}".')
        return True

    logger.info(f'Loading panel segments file "{get_abbrev_path(panel_segments_file)}".')
    with panel_segments_file.open() as f:
        panel_segment_info = json.load(f)

    bw_image = get_bw_image_from_alpha(png_file)

    pil_image = Image.fromarray(cv.merge([bw_image, bw_image, bw_image]))
    assert pil_image.size[0] == panel_segment_info["size"][0]
    assert pil_image.size[1] == panel_segment_info["size"][1]

    img_rects = ImageDraw.Draw(pil_image)
    for box in panel_segment_info["panels"]:
        x0 = box[0]
        y0 = box[1]
        w = box[2]
        h = box[3]
        x1 = x0 + (w - 1)
        y1 = y0 + (h - 1)
        img_rects.rectangle([x0, y0, x1, y1], outline="green", width=10)

    x_min, y_min, x_max, y_max = get_min_max_panel_values(panel_segment_info)
    img_rects.rectangle([x_min, y_min, x_max, y_max], outline="red", width=2)

    # noinspection PyProtectedMember
    img_rects._image.save(str(bounds_img_file))  # noqa: SLF001

    logger.info(f'Saved bounds to image file "{bounds_img_file}".')

    return True


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
