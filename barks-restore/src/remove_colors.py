from collections import OrderedDict
from pathlib import Path

import cv2 as cv
import numpy as np

from .image_io import write_cv_image_file

DEBUG_WRITE_COLOR_COUNTS = True

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
    image_h, image_w = image.shape[0], image.shape[1]

    all_colors = {}

    for i in range(image_h):  ## traverse image row
        for j in range(image_w):  ## traverse image col
            pixel = image[i][j]
            red = int(pixel[2])
            green = int(pixel[1])
            blue = int(pixel[0])

            color = (red, green, blue)

            if color in all_colors:
                all_colors[color] += 1
            else:
                all_colors[color] = 1

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
    work_dir: Path, work_file_stem: str, in_file: Path, out_file: Path
) -> None:
    out_image = cv.imread(str(in_file))

    posterize_image(out_image)
    posterized_image_file = work_dir / (work_file_stem + "-posterized-pre-remove-colors.png")
    write_cv_image_file(posterized_image_file, out_image)

    if DEBUG_WRITE_COLOR_COUNTS:
        posterized_counts_file = work_dir / (
            work_file_stem + "-posterized-color-counts-pre-remove-colors.txt"
        )
        write_color_counts(posterized_counts_file, out_image)

    out_image = cv.cvtColor(str(out_image), cv.COLOR_RGB2RGBA)
    remove_colors(out_image)

    if DEBUG_WRITE_COLOR_COUNTS:
        remaining_color_counts_file = work_dir / (
            work_file_stem + "-remaining-color-counts-post-remove-colors.txt"
        )
        write_color_counts(remaining_color_counts_file, out_image)

    write_cv_image_file(out_file, out_image)
