from pathlib import Path

import cv2 as cv
import numpy as np

from .gmic_exe import run_gmic
from .image_io import write_cv_image_file


def inpaint_image_file(
    work_dir: Path,
    work_file_stem: str,
    in_file: Path,
    black_ink_mask_file: Path,
    out_file: Path,
) -> None:
    if not in_file.is_file():
        msg = f'File not found: "{in_file}".'
        raise FileNotFoundError(msg)
    if not black_ink_mask_file.is_file():
        msg = f'File not found: "{black_ink_mask_file}".'
        raise FileNotFoundError(msg)

    input_image = cv.imread(str(in_file))
    assert input_image.shape[2] == 3  # noqa: PLR2004  # ty: ignore[possibly-missing-attribute]
    black_ink_mask = cv.imread(str(black_ink_mask_file), cv.COLOR_BGR2GRAY)
    assert black_ink_mask.shape[2] == 3  # noqa: PLR2004  # ty: ignore[possibly-missing-attribute]

    _, remove_mask = cv.threshold(black_ink_mask, 100, 255, cv.THRESH_BINARY_INV)
    assert remove_mask.shape[2] == 3  # noqa: PLR2004

    _, _, r_remove_mask = cv.split(remove_mask)

    remove_mask = np.uint8(r_remove_mask)
    remove_mask_file = work_dir / f"{work_file_stem}-remove-mask.png"
    write_cv_image_file(remove_mask_file, remove_mask)

    # gmic blend/remove - pipeline??
    b, g, r = cv.split(input_image)
    b = np.where(remove_mask == 255, 0, b)  # noqa: PLR2004
    g = np.where(remove_mask == 255, 0, g)  # noqa: PLR2004
    r = np.where(remove_mask == 255, 255, r)  # noqa: PLR2004
    out_image = cv.merge([b, g, r])
    in_file_black_removed = work_dir / f"{work_file_stem}-input-black-removed.png"
    write_cv_image_file(in_file_black_removed, out_image)

    inpaint_cmd = [
        str(in_file_black_removed),
        "-fx_inpaint_matchpatch",
        '"1","5","26","5","1","255","0","0","255","1","0"',
        "output",
        str(out_file),
    ]

    run_gmic(inpaint_cmd)
