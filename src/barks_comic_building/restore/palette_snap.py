"""Snap the flat areas of a restored page back to the colours the source was drawn with.

Fantagraphics pages are flat colour under line art, and the source jpgs hold those flats
almost exactly - around 90% of their flat pixels sit on a palette of about ten colours,
with the jpeg noise crowded into a narrow halo along the ink. Upscaling loses that: the
same measurement falls to a quarter or less, because the models put texture into fills
that had none.

The colours are recoverable though, so rather than filtering the drift away it can simply
be replaced with the values the page started with. Only pixels that are both in a flat
region and already close to a palette colour are touched, which leaves every anti-aliased
edge alone.
"""

from pathlib import Path

import cv2 as cv
import numpy as np

from barks_comic_building.restore.image_io import write_cv_image_file

# What counts as a flat area of the source, and of the bigger image being snapped. The
# upscaled image needs the looser pair because its fills carry the drift being corrected.
SRCE_FLAT_KERNEL = 5
SRCE_FLAT_MAX = 4
DEST_FLAT_KERNEL = 9
DEST_FLAT_MAX = 10

# A colour has to hold this share of the source's flat area to count as part of the
# palette, and sit this far from an already kept colour rather than being jpeg noise
# around it.
MIN_PALETTE_SHARE = 0.002
MERGE_DISTANCE = 8

# How close a pixel must already be to a palette colour before it is snapped to it. Wide
# enough to catch the drift, too narrow to reach a pixel that is genuinely between two
# colours.
SNAP_DISTANCE = 14

# Only used to pick out the ink entry, which is either near black or the dark grey that
# 100% K converts to. Kept well below the darkest real flat colours.
INK_MAX_LUMINANCE = 60

# Snapping a whole page at once would need a distance array of tens of gigabytes, and the
# pipeline runs several pages at a time, so the work is done a band of rows at a time.
BLOCK_ROWS = 256

_BGR_LUMINANCE_WEIGHTS = np.array([0.114, 0.587, 0.299])


def _get_flat_mask(image: cv.typing.MatLike, kernel_size: int, max_gradient: int) -> np.ndarray:
    grey = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
    gradient = cv.morphologyEx(
        grey, cv.MORPH_GRADIENT, np.ones((kernel_size, kernel_size), np.uint8)
    )
    return gradient < max_gradient


def get_flat_palette(image: cv.typing.MatLike) -> np.ndarray:
    """Return the exact colours that dominate an image's flat areas, most common first.

    Args:
        image: A BGR image.

    Returns:
        The palette colours as BGR rows.

    """
    flat_pixels = image[_get_flat_mask(image, SRCE_FLAT_KERNEL, SRCE_FLAT_MAX)].reshape(-1, 3)
    if len(flat_pixels) == 0:
        return np.empty((0, 3), dtype=int)

    colours, counts = np.unique(flat_pixels, axis=0, return_counts=True)
    order = np.argsort(-counts)
    colours, counts = colours[order].astype(int), counts[order]

    palette: list[np.ndarray] = []
    for colour, count in zip(colours, counts, strict=True):
        if count < len(flat_pixels) * MIN_PALETTE_SHARE:
            break
        if all(np.linalg.norm(colour - kept) > MERGE_DISTANCE for kept in palette):
            palette.append(colour)

    return np.array(palette) if palette else np.empty((0, 3), dtype=int)


def get_snap_palette(srce_image: cv.typing.MatLike) -> np.ndarray:
    """Return a source's flat palette with its ink colour left out.

    The pipeline snaps the inpainted page, where the ink has already been lifted out and
    filled and will come back as vector black. Keeping ink in the palette could only drag
    inpainted fill towards it, so the darkest entry is dropped when it is dark enough to
    be ink. Real dark flats sit well above that, and stay.

    Args:
        srce_image: The original BGR source page.

    Returns:
        The palette colours as BGR rows.

    """
    palette = get_flat_palette(srce_image)
    if len(palette) == 0:
        return palette

    luminance = palette @ _BGR_LUMINANCE_WEIGHTS
    darkest = int(np.argmin(luminance))
    if luminance[darkest] < INK_MAX_LUMINANCE:
        palette = np.delete(palette, darkest, axis=0)

    return palette


def snap_to_palette(
    image: cv.typing.MatLike, palette: np.ndarray
) -> tuple[cv.typing.MatLike, float]:
    """Replace near-palette pixels in an image's flat areas with the exact palette colour.

    Args:
        image: The BGR image to snap.
        palette: The colours to snap to, as BGR rows.

    Returns:
        The snapped image, and the fraction of its pixels that were changed.

    """
    if len(palette) == 0:
        return image, 0.0

    is_flat = _get_flat_mask(image, DEST_FLAT_KERNEL, DEST_FLAT_MAX)
    snapped = image.copy()
    num_snapped = 0

    palette_f32 = palette.astype(np.float32)
    for start in range(0, image.shape[0], BLOCK_ROWS):
        stop = min(start + BLOCK_ROWS, image.shape[0])
        block = image[start:stop].astype(np.float32)

        # One distance plane per palette colour, keeping only the running best, so the
        # memory stays at a few planes rather than one per colour.
        best_distance = np.full(block.shape[:2], np.inf, dtype=np.float32)
        best_index = np.zeros(block.shape[:2], dtype=np.int16)
        for i, colour in enumerate(palette_f32):
            distance = np.sqrt(((block - colour) ** 2).sum(axis=2))
            is_closer = distance < best_distance
            best_distance[is_closer] = distance[is_closer]
            best_index[is_closer] = i

        mask = is_flat[start:stop] & (best_distance < SNAP_DISTANCE)
        snapped[start:stop][mask] = palette[best_index[mask]]
        num_snapped += int(mask.sum())

    return snapped, num_snapped / (image.shape[0] * image.shape[1])


def snap_image_file_to_srce_palette(srce_file: Path, in_file: Path, out_file: Path) -> float:
    """Snap an image's flat areas to the palette its source page was drawn with.

    Args:
        srce_file: The original source page the palette is taken from.
        in_file: The image to snap.
        out_file: Where to write the snapped image.

    Returns:
        The fraction of pixels that were changed.

    Raises:
        FileNotFoundError: If either input image cannot be read.

    """
    srce_image = cv.imread(str(srce_file))
    if srce_image is None:
        msg = f'Could not read srce file: "{srce_file}".'
        raise FileNotFoundError(msg)

    in_image = cv.imread(str(in_file))
    if in_image is None:
        msg = f'Could not read file to snap: "{in_file}".'
        raise FileNotFoundError(msg)

    palette = get_snap_palette(srce_image)
    del srce_image

    snapped, fraction = snap_to_palette(in_image, palette)
    write_cv_image_file(out_file, snapped)

    return fraction
