from collections import OrderedDict
from pathlib import Path

import cv2 as cv
import numpy as np

from barks_comic_building.restore.image_io import write_cv_image_file

DEBUG_WRITE_COLOR_COUNTS = False

NUM_POSTERIZE_LEVELS = 5
NUM_POSTERIZE_EXCEPTION_LEVELS = 2
FIRST_LEVEL = int(255 / (NUM_POSTERIZE_LEVELS - 1))


def posterize_image(image: cv.typing.MatLike) -> None:
    for i in range(NUM_POSTERIZE_LEVELS):
        image[
            (image >= i * 255 / NUM_POSTERIZE_LEVELS)
            & (image < (i + 1) * 255 / NUM_POSTERIZE_LEVELS)
        ] = i * 255 / (NUM_POSTERIZE_LEVELS - 1)


def remove_colors(image: cv.typing.MatLike) -> None:
    colors_to_remove = np.any(
        [
            image[:, :, 0] > FIRST_LEVEL,
            image[:, :, 1] > FIRST_LEVEL,
            image[:, :, 2] > FIRST_LEVEL,
        ],
        axis=0,
    )
    image[colors_to_remove] = (255, 255, 255, 0)


def get_color_counts(image: cv.typing.MatLike) -> dict[tuple[int, int, int], int]:
    """Count occurrences of each (red, green, blue) colour in a BGR(A) image.

    Vectorized with ``np.unique`` instead of a per-pixel Python loop. Only the first
    three (B, G, R) channels are used; any alpha channel is ignored. Colours are keyed
    in first-occurrence (row-scan) order so that downstream stable sorting by count
    matches the original nested-loop implementation byte-for-byte.
    """
    pixels = image[:, :, :3].reshape(-1, 3)
    unique_bgr, first_index, counts = np.unique(
        pixels, axis=0, return_index=True, return_counts=True
    )

    all_colors: dict[tuple[int, int, int], int] = {}
    for idx in np.argsort(first_index):
        blue, green, red = unique_bgr[idx]
        all_colors[(int(red), int(green), int(blue))] = int(counts[idx])

    return all_colors


def write_color_counts(filename: Path, image: cv.typing.MatLike) -> None:
    color_counts = get_color_counts(image)
    color_counts_descending = OrderedDict(
        sorted(color_counts.items(), key=lambda kv: kv[1], reverse=True)
    )
    with filename.open("w") as f:
        f.writelines(
            f"{color}: {color_counts_descending[color]}\n" for color in color_counts_descending
        )


def remove_colors_from_image(
    work_dir: Path,
    work_file_stem: str,
    in_file: Path,
    out_file: Path,
    debug_color_counts: bool = DEBUG_WRITE_COLOR_COUNTS,
) -> None:
    out_image = cv.imread(str(in_file))
    assert out_image is not None

    posterize_image(out_image)
    posterized_image_file = work_dir / (work_file_stem + "-posterized-pre-remove-colors.png")
    write_cv_image_file(posterized_image_file, out_image)

    if debug_color_counts:
        posterized_counts_file = work_dir / (
            work_file_stem + "-posterized-color-counts-pre-remove-colors.txt"
        )
        write_color_counts(posterized_counts_file, out_image)

    out_image = cv.cvtColor(out_image, cv.COLOR_RGB2RGBA)
    remove_colors(out_image)

    if debug_color_counts:
        remaining_color_counts_file = work_dir / (
            work_file_stem + "-remaining-color-counts-post-remove-colors.txt"
        )
        write_color_counts(remaining_color_counts_file, out_image)

    write_cv_image_file(out_file, out_image)
