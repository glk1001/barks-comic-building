# ruff: noqa: ERA001

from __future__ import annotations

from pathlib import Path

import cv2 as cv
import numpy as np
import typer
from barks_fantagraphics.comic_book import ModifiedType
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_helpers import get_titles
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg  # noqa: TC002
from comic_utils.pil_image_utils import downscale_jpg, load_pil_image_for_reading
from intspan import intspan
from loguru import logger
from loguru_config import LoguruConfig
from skimage.metrics import structural_similarity

APP_LOGGING_NAME = "sdif"

# TODO(glk): Put these somewhere else
SRCE_STANDARD_WIDTH = 2175
SRCE_STANDARD_HEIGHT = 3000


def get_image_diffs(
    diff_thresh: float, image1_file: Path, image2_file: Path
) -> tuple[float, int, cv.typing.MatLike, cv.typing.MatLike]:
    if not image1_file.is_file():
        msg = f'Could not find image1 file "{image1_file}".'
        raise FileNotFoundError(msg)
    if not image2_file.is_file():
        msg = f'Could not find image2 file "{image2_file}".'
        raise FileNotFoundError(msg)

    image1 = cv.imread(str(image1_file))
    image2 = cv.imread(str(image2_file))

    # Use grayscale for the comparison.
    image1_grey = cv.cvtColor(image1, cv.COLOR_BGR2GRAY)  # ty: ignore[no-matching-overload]
    image2_grey = cv.cvtColor(image2, cv.COLOR_BGR2GRAY)  # ty: ignore[no-matching-overload]

    # Compute the SSIM and diff images between the two grayscale images.
    (score, diffs) = structural_similarity(image1_grey, image2_grey, full=True)
    diffs = np.where(diffs < diff_thresh, diffs, 1.0)

    # The diff image contains the actual image differences between the two images and is
    # represented as a floating point data type in the range [0,1]. So convert the array
    # to 8-bit unsigned integers in the range [0,255] before we can use it with OpenCV.
    diffs = (diffs * 255).astype("uint8")

    # Threshold the difference image, followed by finding contours to obtain the regions
    # where the two input images that differ.
    thresh = cv.threshold(diffs, 0, 255, cv.THRESH_BINARY_INV | cv.THRESH_OTSU)[1]
    contours = cv.findContours(thresh.copy(), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    contours = contours[0] if len(contours) == 2 else contours[1]  # noqa: PLR2004

    # mask = np.zeros(image1.shape, dtype="uint8")
    # image2_filled = image2.copy()

    image_width = image1.shape[1]  # ty: ignore[possibly-missing-attribute]
    rect_line_thickness = int(3 * image_width / 2000)
    srce_rect_color = (0, 0, 255)
    fixed_rect_color = (0, 255, 0)

    num_diff_areas = 0
    for c in contours:
        area = cv.contourArea(c)
        if area > 40:  # noqa: PLR2004
            num_diff_areas += 1
            x, y, w, h = cv.boundingRect(c)
            cv.rectangle(image1, (x, y), (x + w, y + h), srce_rect_color, rect_line_thickness)  # ty: ignore[no-matching-overload]
            cv.rectangle(image2, (x, y), (x + w, y + h), fixed_rect_color, rect_line_thickness)  # ty: ignore[no-matching-overload]
            # cv2.drawContours(mask, [c], 0, (0, 255, 0), -1)
            # cv2.drawContours(image2_filled, [c], 0, (0, 255, 0), -1)

    return score, num_diff_areas, image1, image2  # ty: ignore[invalid-return-type]


def show_diffs_for_title(
    comics_database: ComicsDatabase, ttl: str, out_dir: Path
) -> tuple[Path, int]:
    out_dir /= ttl

    logger.info(f'Checking fixes for for "{ttl}"...')

    comic = comics_database.get_comic_book(ttl)

    srce_files = comic.get_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    fixes_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    show_diffs_for_files(ttl + "-orig", out_dir / "orig", srce_files, fixes_files)

    num_diffs = 0

    srce_upscayl_files = comic.get_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)
    fixes_upscayl_files = comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)
    num_diffs += show_diffs_for_upscayled_files(
        ttl + "-upscayl",
        out_dir / "upscayl",
        srce_files,
        srce_upscayl_files,
        fixes_upscayl_files,
    )

    srce_restored_files = comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)
    fixes_restored_files = comic.get_final_srce_story_files(RESTORABLE_PAGE_TYPES)
    num_diffs += show_diffs_for_files(
        ttl + "-restored",
        out_dir / "restored",
        srce_restored_files,
        fixes_restored_files,
    )

    return out_dir, num_diffs


def show_diffs_for_upscayled_files(
    ttl: str,
    out_dir: Path,
    srce_files: list[Path],
    upscayled_srce_files: list[Path],
    upscayled_fixes_files: list[tuple[Path, ModifiedType]],
) -> int:
    logger.info(f'Showing diffs for "{ttl}".')

    num_diffs = 0
    made_out_dir = False
    diff_threshold = 0.5

    for srce_file, upscayled_srce_file, upscayled_fixes_file in zip(
        srce_files, upscayled_srce_files, upscayled_fixes_files, strict=True
    ):
        page_mod_type = upscayled_fixes_file[1]
        if page_mod_type != ModifiedType.MODIFIED:
            continue

        if not made_out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            made_out_dir = True

        assert not upscayled_srce_file.is_file()

        srce_image = load_pil_image_for_reading(srce_file).convert("RGB")
        smaller_fixes_file = Path("/tmp/smaller-fixes-image.jpg")  # noqa: S108
        downscale_jpg(
            srce_image.width, srce_image.height, upscayled_fixes_file[0], smaller_fixes_file
        )

        num_diffs += show_diffs_for_file(
            diff_threshold, ttl, out_dir, srce_file, smaller_fixes_file
        )

    return num_diffs


def show_diffs_for_files(
    ttl: str, out_dir: Path, srce_files: list[Path], fixes_files: list[tuple[Path, ModifiedType]]
) -> int:
    logger.info(f'Showing diffs for "{ttl}".')

    num_diffs = 0
    made_out_dir = False
    diff_threshold = 0.9

    for srce_file, fixes_file in zip(srce_files, fixes_files, strict=True):
        page_mod_type = fixes_file[1]
        if page_mod_type != ModifiedType.MODIFIED:
            continue

        if not made_out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            made_out_dir = True

        num_diffs += show_diffs_for_file(diff_threshold, ttl, out_dir, srce_file, fixes_file[0])

    return num_diffs


def show_diffs_for_file(
    diff_threshold: float, ttl: str, out_dir: Path, srce_file: Path, fixes_file: Path
) -> int:
    logger.info(
        f'Getting diffs for file "{get_abbrev_path(srce_file)}"'
        f' and "{get_abbrev_path(fixes_file)}".'
    )

    ssim, num_diffs, image1_with_diffs, image2_with_diffs = get_image_diffs(
        diff_threshold, srce_file, fixes_file
    )

    page = Path(srce_file).stem

    logger.info(f'"{ttl}-{page}": image similarity = {ssim:.6f}, num diffs = {num_diffs}.')

    if num_diffs == 0:
        return 0

    diff1_file = out_dir / (page + "-1-srce.png")
    diff2_file = out_dir / (page + "-2-fixes.png")
    cv.imwrite(str(diff1_file), image1_with_diffs)
    cv.imwrite(str(diff2_file), image2_with_diffs)
    # cv2.imwrite(os.path.join(out_dir, "diffs.png"), diffs)
    # cv2.imwrite(os.path.join(out_dir, "mask.png"), mask)
    # cv2.imwrite(os.path.join(out_dir, "image2-with-filled-diffs.png"), image2_filled)

    return num_diffs


app = typer.Typer()
log_level = ""


@app.command(help="Show fixes diffs for volume or title")
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

    output_dir = Path("/tmp/fixes-diffs")  # noqa: S108

    for title in get_titles(comics_database, volumes, title_str):
        title_out_dir, n_diffs = show_diffs_for_title(comics_database, title, output_dir)

        if n_diffs > 0:
            logger.info(f'{n_diffs} diff files written to "{title_out_dir}".')


if __name__ == "__main__":
    app()
