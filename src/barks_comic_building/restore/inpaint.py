from pathlib import Path

import cv2 as cv
import numpy as np

from barks_comic_building.restore.gmic_exe import run_gmic
from barks_comic_building.restore.image_io import write_cv_image_file

# gmic 'fx_inpaint_matchpatch' parameters (fixed). Named so that the restore recipe can
# record what the colour layer was filled with.
GMIC_INPAINT_MATCHPATCH_PARAMS = '"1","5","26","5","1","255","0","0","255","1","0"'

# Clamped to the 8-bit range before it is written, because matchpatch blends its way a
# little past white - 258 and 259 were measured on volume 4's page 098 - and gmic answers a
# value over 255 by writing a 16 bit png. Nothing else here reads one: PIL and OpenCV both
# rescale 16 bit down by dividing by 257, so a page holding 0 to 259 arrives as every pixel
# zero. That is what made 098 and 099 look like blank pages for a whole day of investigation
# while the files on disk were perfectly good, and it is why the fix belongs here, at the one
# step that produces the out-of-range values, rather than in the readers.
#
# A no-op for every page that already fitted, and outside the recipe id - which is built from
# `GMIC_INPAINT_MATCHPATCH_PARAMS`, not from the command - so nothing already restored goes
# stale over it.
_GMIC_CLAMP_TO_8_BIT = ("cut", "0,255")


def inpaint_image_file(
    work_dir: Path,
    work_file_stem: str,
    in_file: Path,
    black_ink_mask_file: Path,
    out_file: Path,
) -> None:
    """Fill an image's black ink areas with colour taken from around them.

    Args:
        work_dir: Where the intermediates are written.
        work_file_stem: What to name them after.
        in_file: The colour page to fill.
        black_ink_mask_file: The colour-removed page, dark where the ink is.
        out_file: Where to write the filled page.

    Raises:
        FileNotFoundError: If either input image is missing.

    """
    if not in_file.is_file():
        msg = f'File not found: "{in_file}".'
        raise FileNotFoundError(msg)
    if not black_ink_mask_file.is_file():
        msg = f'File not found: "{black_ink_mask_file}".'
        raise FileNotFoundError(msg)

    input_image = cv.imread(str(in_file))
    assert input_image is not None
    assert input_image.shape[2] == 3  # noqa: PLR2004
    black_ink_mask = cv.imread(str(black_ink_mask_file), cv.IMREAD_COLOR)
    assert black_ink_mask is not None
    assert black_ink_mask.shape[2] == 3  # noqa: PLR2004

    _, remove_mask = cv.threshold(black_ink_mask, 100, 255, cv.THRESH_BINARY_INV)
    assert remove_mask.shape[2] == 3  # noqa: PLR2004

    _, _, r_remove_mask = cv.split(remove_mask)

    remove_mask = np.uint8(r_remove_mask)
    remove_mask_file = work_dir / f"{work_file_stem}-remove-mask.png"
    write_cv_image_file(remove_mask_file, remove_mask)  # ty: ignore[invalid-argument-type]

    # gmic blend/remove - pipeline??
    b, g, r = cv.split(input_image)
    b = np.where(remove_mask == 255, 0, b)  # noqa: PLR2004
    g = np.where(remove_mask == 255, 0, g)  # noqa: PLR2004
    r = np.where(remove_mask == 255, 255, r)  # noqa: PLR2004
    out_image = cv.merge([b, g, r])
    in_file_black_removed = work_dir / f"{work_file_stem}-input-black-removed.png"
    write_cv_image_file(in_file_black_removed, out_image)

    run_gmic(
        [
            str(in_file_black_removed),
            "-fx_inpaint_matchpatch",
            GMIC_INPAINT_MATCHPATCH_PARAMS,
            *_GMIC_CLAMP_TO_8_BIT,
            "output",
            str(out_file),
        ]
    )
