# ruff: noqa: ERA001, PTH118, S108, ANN001, ANN202

import os

import cv2 as cv
import numpy as np
from numba import jit

DEBUG = False
DEBUG_OUTPUT_DIR = "/tmp"

MEDIAN_BLUR_APERTURE_SIZE = 7
ADAPTIVE_THRESHOLD_BLOCK_SIZE = 21
ADAPTIVE_THRESHOLD_CONST_SUBTRACT = 12  # Careful here with including alias artifacts


def _median_filter(
    original_image: cv.typing.MatLike, mask: cv.typing.MatLike, kernel_size: int
) -> cv.typing.MatLike:
    filtered_image = np.zeros_like(original_image)
    w = kernel_size // 2

    wrapped_image = cv.copyMakeBorder(
        original_image, w, w, w, w, cv.BORDER_CONSTANT, None, value=(255, 255, 255)
    )
    wrapped_mask = cv.copyMakeBorder(
        mask, w, w, w, w, cv.BORDER_CONSTANT, None, value=(255, 255, 255)
    )

    if DEBUG:
        cv.imwrite(
            os.path.join(DEBUG_OUTPUT_DIR, "wrapped-image.jpg"),
            wrapped_image,
        )
        cv.imwrite(
            os.path.join(DEBUG_OUTPUT_DIR, "wrapped-mask.jpg"),
            wrapped_mask,
        )

    _median_filter_core(wrapped_image, wrapped_mask, kernel_size, filtered_image)

    #    median_filter_core.parallel_diagnostics(level=4)

    return filtered_image


@jit(nopython=True, parallel=False)
def _median_filter_core(
    wrapped_image: cv.typing.MatLike,
    wrapped_mask: cv.typing.MatLike,
    kernel_size: int,
    filtered_image: cv.typing.MatLike,
) -> None:
    image_h, image_w = filtered_image.shape[0], filtered_image.shape[1]
    w: int = kernel_size // 2

    nbrs0 = np.empty((kernel_size * kernel_size, 1), dtype=filtered_image.dtype)
    nbrs1 = np.empty((kernel_size * kernel_size, 1), dtype=filtered_image.dtype)
    nbrs2 = np.empty((kernel_size * kernel_size, 1), dtype=filtered_image.dtype)

    for i in range(w, image_h + w):
        for j in range(w, image_w + w):
            if wrapped_mask[i, j] > 0:
                filtered_image[i - w, j - w] = wrapped_image[i, j]
                continue
            num_nbrs = 0
            for x in range(i - w, i + w + 1):
                for y in range(j - w, j + w + 1):
                    if wrapped_mask[x, y] > 0:
                        continue
                    pixel = wrapped_image[x, y]
                    nbrs0[num_nbrs] = pixel[0]
                    nbrs1[num_nbrs] = pixel[1]
                    nbrs2[num_nbrs] = pixel[2]
                    num_nbrs += 1
            filtered_image[i - w, j - w] = _get_median(num_nbrs, nbrs0, nbrs1, nbrs2)


@jit(nopython=True, parallel=False)
def _get_median(num_nbrs: int, nbrs0, nbrs1, nbrs2):
    if num_nbrs == 0:
        return 0, 100, 0

    if num_nbrs == nbrs0.size:
        return np.median(nbrs0), np.median(nbrs1), np.median(nbrs2)

    return (
        np.median(nbrs0[:num_nbrs]),
        np.median(nbrs1[:num_nbrs]),
        np.median(nbrs2[:num_nbrs]),
    )


def get_median_filter(input_image: cv.typing.MatLike) -> cv.typing.MatLike:
    black_ink_mask = _get_black_ink_mask(input_image)
    if DEBUG:
        cv.imwrite(
            os.path.join(DEBUG_OUTPUT_DIR, "median-black-ink-mask.jpg"),
            black_ink_mask,
        )

    black_ink_mask_blurred_image = cv.GaussianBlur(255 - black_ink_mask, (3, 3), 0)

    ret, enlarged_black_ink_mask = cv.threshold(
        black_ink_mask_blurred_image, 200.0, 255, cv.THRESH_BINARY_INV
    )
    if DEBUG:
        cv.imwrite(
            os.path.join(DEBUG_OUTPUT_DIR, "enlarged-black-ink-mask-median.jpg"),
            enlarged_black_ink_mask,
        )

    filtered_image = _median_filter(input_image, enlarged_black_ink_mask, MEDIAN_BLUR_APERTURE_SIZE)
    if DEBUG:
        cv.imwrite(
            os.path.join(DEBUG_OUTPUT_DIR, "median-filtered-image.jpg"),
            filtered_image,
        )

    return filtered_image


def _get_black_ink_mask(image: cv.typing.MatLike) -> cv.typing.MatLike:
    gray_image = cv.cvtColor(image, cv.COLOR_BGR2GRAY)

    return cv.adaptiveThreshold(
        gray_image,
        255,
        cv.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv.THRESH_BINARY_INV,
        ADAPTIVE_THRESHOLD_BLOCK_SIZE,
        ADAPTIVE_THRESHOLD_CONST_SUBTRACT,
    )
