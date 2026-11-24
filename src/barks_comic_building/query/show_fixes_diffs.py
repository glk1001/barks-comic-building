"""Write images showing where each fixed page of a title differs from its scan."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import cv2 as cv
import numpy as np
import typer
from barks_fantagraphics.comic_book import ModifiedType
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg  # noqa: TC002
from comic_utils.pil_image_utils import downscale_jpg, load_pil_image_for_reading
from loguru import logger
from skimage.metrics import structural_similarity

from barks_comic_building.cli_setup import get_comic_titles, init_logging

if TYPE_CHECKING:
    from barks_fantagraphics.comics_database import ComicsDatabase

APP_LOGGING_NAME = "sdif"

DEFAULT_OUTPUT_DIR = Path("/tmp/fixes-diffs")  # noqa: S108


def get_image_diffs(
    diff_thresh: float, image1_file: Path, image2_file: Path
) -> tuple[float, int, cv.typing.MatLike, cv.typing.MatLike]:
    """Compare two images of the same size and box the areas where they differ.

    Args:
        diff_thresh: How alike the area around a pixel must be, from 0 to 1, for it not
            to count as a difference.
        image1_file: The image before the fix.
        image2_file: The image after it.

    Returns:
        The images' structural similarity, the number of areas that differ, and each
        image with those areas boxed.

    Raises:
        FileNotFoundError: If either image is missing.

    """
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

    image_width = image1.shape[1]  # ty: ignore[missing-union-attribute]
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

    return score, num_diff_areas, image1, image2  # ty: ignore[invalid-return-type]


def show_diffs_for_title(
    comics_database: ComicsDatabase, ttl: str, out_dir: Path
) -> tuple[Path, int]:
    """Write the diff images for every fixed page of a title.

    Args:
        comics_database: The database to open the title in.
        ttl: The title.
        out_dir: The directory to write the title's diff images under.

    Returns:
        The number of differing areas found, over the original and the upscayled fixes.

    """
    out_dir /= ttl

    logger.info(f'Checking fixes for for "{ttl}"...')

    comic = comics_database.get_comic_book(ttl)

    srce_files = comic.get_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    fixes_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    num_diffs = show_diffs_for_files(ttl + "-orig", out_dir / "orig", srce_files, fixes_files)

    srce_upscayl_files = comic.get_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)
    fixes_upscayl_files = comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)
    num_diffs += show_diffs_for_upscayled_files(
        ttl + "-upscayl",
        out_dir / "upscayl",
        srce_files,
        srce_upscayl_files,
        fixes_upscayl_files,
    )

    # There is no "restored" stage. A restored page has no fix to compare it with - the
    # file the build uses for it *is* the restored page - so that stage could never show
    # a diff, and asking for the build's files raised on the first page not restored yet
    # and took the rest of the volume down with it.

    return out_dir, num_diffs


def show_diffs_for_upscayled_files(
    ttl: str,
    out_dir: Path,
    srce_files: list[Path],
    upscayled_srce_files: list[Path],
    upscayled_fixes_files: list[tuple[Path, ModifiedType]],
) -> int:
    """Write the diff images for a title's upscayled fixes.

    An upscayled fix has no upscayled file to compare with - a page may not have both -
    so it is scaled down and compared with the scan.

    Args:
        ttl: The title, for the log.
        out_dir: The directory to write the diff images in.
        srce_files: Each page's scan.
        upscayled_srce_files: Each page's upscayled file, which a fixed page must not have.
        upscayled_fixes_files: Each page's upscayled file or fix, and which of them it is.

    Returns:
        The number of differing areas found.

    """
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
        # A scratch file of this run's own. It had one fixed name in /tmp, so two runs at
        # once compared one's scan with the other's fix and drew boxes round the result.
        with tempfile.TemporaryDirectory(prefix="fixes-diffs-") as scratch_dir:
            smaller_fixes_file = Path(scratch_dir) / "smaller-fixes-image.jpg"
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
    """Write the diff images for a title's fixes of the original scans.

    Args:
        ttl: The title, for the log.
        out_dir: The directory to write the diff images in.
        srce_files: Each page's scan.
        fixes_files: Each page's scan or fix, and which of them it is.

    Returns:
        The number of differing areas found.

    """
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
    """Write the diff images for one fixed page, if the fix differs from the scan.

    Args:
        diff_threshold: How alike the area around a pixel must be not to count.
        ttl: The title, for the log.
        out_dir: The directory to write the two diff images in.
        srce_file: The page before the fix.
        fixes_file: The page after it, the same size.

    Returns:
        The number of differing areas found.

    """
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

    return num_diffs


app = typer.Typer()


@app.command(help="Show fixes diffs for volume or title")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "DEBUG",
    output_dir: Annotated[
        Path, typer.Option("--output-dir", help="Where to write each title's diff images.")
    ] = DEFAULT_OUTPUT_DIR,
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    for title in titles:
        title_out_dir, n_diffs = show_diffs_for_title(comics_database, title, output_dir)

        if n_diffs > 0:
            logger.info(f'{n_diffs} diff files written to "{title_out_dir}".')


if __name__ == "__main__":
    app()
