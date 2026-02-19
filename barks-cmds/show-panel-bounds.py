import json
from pathlib import Path

import cv2 as cv
import typer
from barks_fantagraphics.comics_consts import PNG_FILE_EXT, RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.common_typer_options import LogLevelArg, TitleArg
from comic_utils.cv_image_utils import get_bw_image_from_alpha
from loguru import logger
from loguru_config import LoguruConfig
from PIL import Image, ImageDraw

APP_LOGGING_NAME = "span"


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
        bw_image = get_bw_image_from_alpha(png_file)
        pil_image = Image.fromarray(cv.merge([bw_image, bw_image, bw_image])).convert("RGBA")
        if not write_bounds_to_pil_image(pil_image, panel_segments_file):
            msg = "There were process errors."
            raise RuntimeError(msg)
        pil_image.save(bounds_img_file)

    logger.info(f'Finished generating panel bounds images for "{title}" to directory "{out_dir}".')


def write_bounds_to_pil_image(
    pil_image: Image.Image, panel_segments_file: Path, include_overall_bound: bool = True
) -> bool:
    logger.info(
        f'Writing bounds using segments info file "{get_abbrev_path(panel_segments_file)}"...'
    )

    if not panel_segments_file.is_file():
        logger.error(f'Could not find panel segments file "{panel_segments_file}".')
        return False

    logger.info(f'Loading panel segments file "{get_abbrev_path(panel_segments_file)}".')
    with panel_segments_file.open("r") as f:
        panel_segment_info = json.load(f)

    if pil_image.size[0] != panel_segment_info["size"][0]:
        msg = (
            f"Image size[0] {pil_image.size[0]}"
            f" does not match panel segment info size[0] {panel_segment_info['size'][0]}."
        )
        raise RuntimeError(msg)
    if pil_image.size[1] != panel_segment_info["size"][1]:
        msg = (
            f"Image size[1] {pil_image.size[1]}"
            f" does not match panel segment info size[1] {panel_segment_info['size'][1]}."
        )
        raise RuntimeError(msg)

    draw = ImageDraw.Draw(pil_image)
    for box in panel_segment_info["panels"]:
        x0 = box[0]
        y0 = box[1]
        w = box[2]
        h = box[3]
        x1 = x0 + (w - 1)
        y1 = y0 + (h - 1)
        draw.rectangle([x0, y0, x1, y1], outline="green", width=10)

    if include_overall_bound:
        x0, y0, x1, y1 = panel_segment_info["overall_bounds"]
        draw.rectangle([x0, y0, x1, y1], outline="red", width=2)

    return True


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
