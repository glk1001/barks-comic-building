# ruff: noqa: T201, ERA001

from __future__ import annotations

import logging
import os.path
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from barks_fantagraphics.comic_book import ModifiedType
from barks_fantagraphics.comics_cmd_args import CmdArgNames, CmdArgs
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_logging import setup_logging
from barks_fantagraphics.pil_image_utils import downscale_jpg
from cv2 import Mat
from skimage.metrics import structural_similarity

# TODO: Put these somewhere else
SRCE_STANDARD_WIDTH = 2175
SRCE_STANDARD_HEIGHT = 3000


def get_image_diffs(
    diff_thresh: float, image1_file: str, image2_file: str
) -> tuple[float, int, Mat | np.ndarray[Any, np.dtype], Mat | np.ndarray[Any, np.dtype]]:
    if not os.path.isfile(image1_file):
        raise FileNotFoundError(f'Could not find image1 file "{image1_file}".')
    if not os.path.isfile(image2_file):
        raise FileNotFoundError(f'Could not find image2 file "{image2_file}".')

    image1 = cv2.imread(image1_file)
    image2 = cv2.imread(image2_file)

    # Use grayscale for the comparison.
    image1_grey = cv2.cvtColor(image1, cv2.COLOR_BGR2GRAY)
    image2_grey = cv2.cvtColor(image2, cv2.COLOR_BGR2GRAY)

    # Compute the SSIM and diff images between the two grayscale images.
    (score, diffs) = structural_similarity(image1_grey, image2_grey, full=True)
    diffs = np.where(diffs < diff_thresh, diffs, 1.0)

    # The diff image contains the actual image differences between the two images and is
    # represented as a floating point data type in the range [0,1]. So convert the array
    # to 8-bit unsigned integers in the range [0,255] before we can use it with OpenCV.
    diffs = (diffs * 255).astype("uint8")

    # Threshold the difference image, followed by finding contours to obtain the regions
    # where the two input images that differ.
    thresh = cv2.threshold(diffs, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    contours = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = contours[0] if len(contours) == 2 else contours[1]

    # mask = np.zeros(image1.shape, dtype="uint8")
    # image2_filled = image2.copy()

    image_width = image1.shape[1]
    rect_line_thickness = int(3 * image_width / 2000)
    srce_rect_color = (0, 0, 255)
    fixed_rect_color = (0, 255, 0)

    num_diff_areas = 0
    for c in contours:
        area = cv2.contourArea(c)
        if area > 40:
            num_diff_areas += 1
            x, y, w, h = cv2.boundingRect(c)
            cv2.rectangle(image1, (x, y), (x + w, y + h), srce_rect_color, rect_line_thickness)
            cv2.rectangle(image2, (x, y), (x + w, y + h), fixed_rect_color, rect_line_thickness)
            # cv2.drawContours(mask, [c], 0, (0, 255, 0), -1)
            # cv2.drawContours(image2_filled, [c], 0, (0, 255, 0), -1)

    return score, num_diff_areas, image1, image2


def show_diffs_for_title(ttl: str, out_dir: str) -> None:
    out_dir = os.path.join(out_dir, ttl)

    logging.info(f'Checking fixes for for "{ttl}"...')

    comic = comics_database.get_comic_book(ttl)

    srce_files = comic.get_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    fixes_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    show_diffs_for_files(ttl + "-orig", os.path.join(out_dir, "orig"), srce_files, fixes_files)

    srce_upscayl_files = comic.get_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)
    fixes_upscayl_files = comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)
    show_diffs_for_upscayled_files(
        ttl + "-upscayl",
        os.path.join(out_dir, "upscayl"),
        srce_files,
        srce_upscayl_files,
        fixes_upscayl_files,
    )

    srce_restored_files = comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)
    fixes_restored_files = comic.get_final_srce_story_files(RESTORABLE_PAGE_TYPES)
    show_diffs_for_files(
        ttl + "-restored",
        os.path.join(out_dir, "restored"),
        srce_restored_files,
        fixes_restored_files,
    )


def show_diffs_for_upscayled_files(
    ttl: str,
    out_dir: str,
    srce_files: list[str],
    upscayled_srce_files: list[str],
    upscayled_fixes_files: list[tuple[str, ModifiedType]],
) -> None:
    made_out_dir = False
    diff_threshold = 0.5

    for srce_file, upscayled_srce_file, upscayled_fixes_file in zip(
        srce_files, upscayled_srce_files, upscayled_fixes_files
    ):
        page_mod_type = upscayled_fixes_file[1]
        if page_mod_type != ModifiedType.MODIFIED:
            continue

        if not made_out_dir:
            os.makedirs(out_dir, exist_ok=True)
            made_out_dir = True

        assert not os.path.isfile(upscayled_srce_file)

        smaller_fixes_file = "/tmp/smaller-fixes-image.jpg"
        downscale_jpg(
            SRCE_STANDARD_WIDTH, SRCE_STANDARD_HEIGHT, upscayled_fixes_file[0], smaller_fixes_file
        )

        show_diffs_for_file(diff_threshold, ttl, out_dir, srce_file, smaller_fixes_file)


def show_diffs_for_files(
    ttl: str, out_dir: str, srce_files: list[str], fixes_files: list[tuple[str, ModifiedType]]
) -> None:
    made_out_dir = False
    diff_threshold = 0.9

    for srce_file, fixes_file in zip(srce_files, fixes_files):
        page_mod_type = fixes_file[1]
        if page_mod_type != ModifiedType.MODIFIED:
            continue

        if not made_out_dir:
            os.makedirs(out_dir, exist_ok=True)
            made_out_dir = True

        show_diffs_for_file(diff_threshold, ttl, out_dir, srce_file, fixes_file[0])


def show_diffs_for_file(
    diff_threshold: float, ttl: str, out_dir: str, srce_file: str, fixes_file: str
) -> None:
    ssim, num_diffs, image1_with_diffs, image2_with_diffs = get_image_diffs(
        diff_threshold, srce_file, fixes_file
    )

    page = Path(srce_file).stem

    print(f'"{ttl}-{page}": image similarity = {ssim:.6f}, num diffs = {num_diffs}.')

    if num_diffs == 0:
        return

    diff1_file = os.path.join(out_dir, page + "-1-srce.png")
    diff2_file = os.path.join(out_dir, page + "-2-fixes.png")
    cv2.imwrite(diff1_file, image1_with_diffs)
    cv2.imwrite(diff2_file, image2_with_diffs)
    # cv2.imwrite(os.path.join(out_dir, "diffs.png"), diffs)
    # cv2.imwrite(os.path.join(out_dir, "mask.png"), mask)
    # cv2.imwrite(os.path.join(out_dir, "image2-with-filled-diffs.png"), image2_filled)


if __name__ == "__main__":
    # TODO(glk): Some issue with type checking inspection?
    # noinspection PyTypeChecker
    cmd_args = CmdArgs("show fixes diffs", CmdArgNames.VOLUME | CmdArgNames.TITLE)
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logging.error(error_msg)
        sys.exit(1)

    setup_logging(cmd_args.get_log_level())

    comics_database = cmd_args.get_comics_database()

    output_dir = "/tmp/fixes-diffs"

    for title in cmd_args.get_titles():
        show_diffs_for_title(title, output_dir)
