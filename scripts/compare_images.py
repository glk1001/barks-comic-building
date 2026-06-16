import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from loguru import logger


@dataclass
class CompareError:
    """A single comparison error, suitable for tabular reporting.

    Attributes:
        error_type: The category of error (e.g. "image", "file-diff").
        file: The file the error relates to.
        detail: Short context shown in the summary table (e.g. an image metric
            value, or a short "diff" marker for a file difference).

    """

    error_type: str
    file: str
    detail: str = ""


def compare_images_in_dir(  # noqa: PLR0913
    dir1: Path,
    dir2: Path,
    fuzz: str,
    ae_cutoff: float,
    diff_dir: Path | None,
    ae_cutoff_pct: float | None = None,
    calibrate: bool = False,
    tile_size: int | None = None,
    tile_cutoff_pct: float | None = None,
) -> list[CompareError]:
    """Compare every image in `dir1` against its counterpart in `dir2`.

    Args:
        dir1: First image directory.
        dir2: Second image directory.
        fuzz: Fuzz factor (e.g. "5%"). "0%" uses the RMSE metric, otherwise AE.
        ae_cutoff: Absolute AE pixel-count cutoff above which an image is flagged.
        diff_dir: Directory for diff images (required for non-zero fuzz).
        ae_cutoff_pct: AE cutoff as a percentage of each image's total pixels.
            When set it overrides `ae_cutoff` per image (resolution-independent).
        calibrate: When True, log the per-image AE (or worst-tile) figure at
            `fuzz` without applying any cutoff, and return no errors.
        tile_size: When set, compare regionally: split each page into ~this-size
            (px) tiles and flag the image if any tile differs too much. Replaces
            the whole-page AE cutoff and uses `tile_cutoff_pct`.
        tile_cutoff_pct: In tiled mode, flag the image if any tile's
            differing-pixel percentage exceeds this.

    Returns:
        A list of comparison errors (empty in calibration mode).

    """
    _validate_compare_inputs(
        dir1,
        dir2,
        fuzz,
        ae_cutoff,
        ae_cutoff_pct,
        diff_dir,
        tile_size=tile_size,
        tile_cutoff_pct=tile_cutoff_pct,
        calibrate=calibrate,
    )

    files_in_dir1 = sorted(f for f in dir1.iterdir() if f.is_file())

    if calibrate:
        if tile_size is not None:
            calibrate_tiles_in_dir(dir1, dir2, fuzz, tile_size, files_in_dir1, diff_dir)
        else:
            calibrate_ae_in_dir(dir1, dir2, fuzz, files_in_dir1)
        return []

    errors: list[CompareError] = []
    for image_file1 in files_in_dir1:
        image_file2 = get_image_file2(dir2, image_file1)
        if not image_file2:
            # No counterpart in dir2 (get_image_file2 has already logged a
            # warning). Record it so the comparison is reported as failed.
            errors.append(
                CompareError(
                    error_type="image-missing",
                    file=f'"{image_file1}"',
                    detail="no corresponding file",
                )
            )
            continue

        error = compare_one_image(
            image_file1,
            image_file2,
            fuzz,
            ae_cutoff,
            ae_cutoff_pct,
            diff_dir,
            tile_size=tile_size,
            tile_cutoff_pct=tile_cutoff_pct,
        )
        if error is not None:
            errors.append(error)

    return errors


def _validate_compare_inputs(  # noqa: PLR0913
    dir1: Path,
    dir2: Path,
    fuzz: str,
    ae_cutoff: float,
    ae_cutoff_pct: float | None,
    diff_dir: Path | None,
    *,
    tile_size: int | None,
    tile_cutoff_pct: float | None,
    calibrate: bool,
) -> None:
    """Validate `compare_images_in_dir` arguments, raising on bad input."""
    if not dir1.is_dir():
        msg = f'Error: Could not find directory1: "{dir1}".'
        raise FileNotFoundError(msg)
    if not dir2.is_dir():
        msg = f'Error: Could not find directory2: "{dir2}".'
        raise FileNotFoundError(msg)
    if not fuzz.endswith("%"):
        msg = f"Error: The fuzz amount must end with a '%': \"{fuzz}\"."
        raise ValueError(msg)

    if tile_size is not None:
        _validate_tile_inputs(tile_size, tile_cutoff_pct, diff_dir, calibrate=calibrate)
    else:
        _validate_ae_inputs(fuzz, ae_cutoff, ae_cutoff_pct, diff_dir, calibrate=calibrate)


def _validate_tile_inputs(
    tile_size: int, tile_cutoff_pct: float | None, diff_dir: Path | None, *, calibrate: bool
) -> None:
    """Validate the tiled-comparison arguments."""
    if tile_size <= 0:
        msg = f'Error: "tile_size" must be positive: "{tile_size}".'
        raise ValueError(msg)
    if not diff_dir:
        msg = "Error: Tiled comparison requires a diff dir (for the tile masks)."
        raise ValueError(msg)
    if tile_cutoff_pct is not None and tile_cutoff_pct <= 0.0:
        msg = f'Error: "tile_cutoff_pct" must be positive: "{tile_cutoff_pct}".'
        raise ValueError(msg)
    if tile_cutoff_pct is None and not calibrate:
        msg = 'Error: You must specify "tile_cutoff_pct" for tiled comparison.'
        raise ValueError(msg)


def _validate_ae_inputs(
    fuzz: str,
    ae_cutoff: float,
    ae_cutoff_pct: float | None,
    diff_dir: Path | None,
    *,
    calibrate: bool,
) -> None:
    """Validate the whole-page AE/RMSE arguments."""
    if ae_cutoff_pct is not None and ae_cutoff_pct <= 0.0:
        msg = f'Error: "ae_cutoff_pct" must be positive: "{ae_cutoff_pct}".'
        raise ValueError(msg)

    if fuzz != "0%" and not calibrate:
        if not diff_dir:
            msg = f'Error: For non-zero fuzz amount "{fuzz}" you must specify a diff dir.'
            raise ValueError(msg)
        if ae_cutoff_pct is None and ae_cutoff <= 0.0001:  # noqa: PLR2004
            msg = (
                'Error: You must specify a non-zero "ae_cutoff" or "ae_cutoff_pct" '
                "for non-zero fuzz."
            )
            raise ValueError(msg)

    if ae_cutoff_pct is not None and fuzz == "0%" and not calibrate:
        logger.warning('"ae_cutoff_pct" is ignored at 0% fuzz (RMSE metric).')


def compare_one_image(  # noqa: PLR0913
    image_file1: Path,
    image_file2: Path,
    fuzz: str,
    ae_cutoff: float,
    ae_cutoff_pct: float | None,
    diff_dir: Path | None,
    *,
    tile_size: int | None = None,
    tile_cutoff_pct: float | None = None,
) -> CompareError | None:
    """Compare a single image pair, returning a CompareError if they differ.

    In tiled mode (`tile_size` set) the page is compared region by region. Else
    the whole page is compared: when `ae_cutoff_pct` is given the cutoff is
    derived from the first image's total pixel count, otherwise `ae_cutoff`.

    Returns:
        A CompareError if the images differ beyond the cutoff, else None.

    """
    logger.info(f'Comparing "{image_file1.name}"...')

    if tile_size is not None:
        assert tile_cutoff_pct is not None
        assert diff_dir is not None
        result_code, metric = compare_images_tiled(
            image_file1, image_file2, fuzz, tile_size, tile_cutoff_pct, diff_dir
        )
    else:
        cutoff = ae_cutoff
        if ae_cutoff_pct is not None:
            total_pixels = get_pixel_count(image_file1)
            cutoff = ae_cutoff_pct / 100.0 * total_pixels if total_pixels else ae_cutoff
        result_code, metric = compare_images(image_file1, image_file2, fuzz, cutoff, diff_dir)

    if result_code == 0:
        return None

    logger.error(f"Compare error: {result_code}, {metric}.")
    return CompareError(error_type="image", file=f'"{image_file1}"\n"{image_file2}"', detail=metric)


def calibrate_ae_in_dir(dir1: Path, dir2: Path, fuzz: str, files_in_dir1: list[Path]) -> None:
    """Log the AE pixel count for each image pair to help choose a cutoff.

    For every file in `files_in_dir1` that has a counterpart in `dir2`, log the
    absolute-error pixel count at the given `fuzz` (and as a percentage of the
    image's total pixels), then log the maximum seen. No cutoff is applied.

    Args:
        dir1: First image directory.
        dir2: Second image directory.
        fuzz: Fuzz factor used when counting differing pixels.
        files_in_dir1: The files in `dir1` to measure.

    """
    logger.info(f'Calibrating AE counts in "{dir1}" at fuzz {fuzz}...')
    max_count = 0
    max_name = ""
    max_pct = 0.0
    for image_file1 in files_in_dir1:
        image_file2 = get_image_file2(dir2, image_file1)
        if not image_file2:
            continue

        count = get_ae_pixel_count(image_file1, image_file2, fuzz)
        if count is None:
            logger.warning(f'Could not measure AE for "{image_file1.name}".')
            continue

        total_pixels = get_pixel_count(image_file1)
        pct = (100.0 * count / total_pixels) if total_pixels else 0.0
        logger.info(f"  {image_file1.name}: AE={count} ({pct:.3f}% of {total_pixels} px)")

        if count > max_count:
            max_count, max_name, max_pct = count, image_file1.name, pct

    if max_count:
        logger.info(f'Max AE for "{dir1}": {max_count} px ({max_pct:.3f}%) ("{max_name}").')


def get_dimensions(image: Path) -> tuple[int, int] | None:
    """Return the (width, height) of an image via ImageMagick `identify`.

    Args:
        image: Path to the image.

    Returns:
        A (width, height) tuple, or None if it could not be determined.

    """
    command = ["identify", "-format", "%w %h", str(image)]
    proc = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603
    try:
        width, height = proc.stdout.split()[:2]
        return int(width), int(height)
    except (ValueError, IndexError):
        return None


def get_pixel_count(image: Path) -> int:
    """Return the total pixel count (width * height) of an image, or 0 on error."""
    dims = get_dimensions(image)
    return dims[0] * dims[1] if dims else 0


def get_ae_pixel_count(file1: Path, file2: Path, fuzz: str) -> int | None:
    """Return the AE (absolute error) pixel count between two images at a fuzz.

    Uses ImageMagick `compare` writing to `null:` so no diff image is produced.

    Args:
        file1: Path to the first image.
        file2: Path to the second image.
        fuzz: The fuzz factor (e.g. "5%").

    Returns:
        The number of differing pixels, or None if it could not be parsed.

    """
    command = ["compare", "-metric", "AE", "-fuzz", fuzz, str(file1), str(file2), "null:"]
    proc = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603
    metric_output = proc.stderr.strip()
    try:
        return int(float(metric_output.split()[0]))
    except (ValueError, IndexError):
        return None


def get_tile_diff_fractions(
    file1: Path, file2: Path, fuzz: str, tile_size: int, mask_path: Path
) -> tuple[list[float], int, int] | None:
    """Return the per-tile fraction of differing pixels between two images.

    A binary diff mask (pixels differing beyond `fuzz` are white, the rest
    black) is written to `mask_path`, then split into a grid of roughly
    `tile_size`-pixel tiles; the mean of each tile is its differing-pixel
    fraction (0.0-1.0).

    Args:
        file1: Path to the first image.
        file2: Path to the second image.
        fuzz: The fuzz factor (e.g. "20%").
        tile_size: Target tile edge length in pixels; the grid is derived per
            image so tiles are about this size.
        mask_path: Where to write the binary diff mask.

    Returns:
        A tuple of (fractions, cols, rows) in row-major tile order, or None if
        the images could not be compared (unreadable or differing dimensions).

    """
    dims1 = get_dimensions(file1)
    dims2 = get_dimensions(file2)
    if dims1 is None or dims2 is None or dims1 != dims2:
        return None
    width, height = dims1
    cols = max(1, round(width / tile_size))
    rows = max(1, round(height / tile_size))

    mask_path.parent.mkdir(parents=True, exist_ok=True)
    compare_cmd = [
        "compare",
        "-fuzz",
        fuzz,
        "-highlight-color",
        "white",
        "-lowlight-color",
        "black",
        str(file1),
        str(file2),
        str(mask_path),
    ]
    # compare exits 1 when images differ (expected) and 2 on a hard error
    # (e.g. mismatched dimensions), in which case the mask is unusable.
    proc = subprocess.run(compare_cmd, check=False, capture_output=True, text=True)  # noqa: S603
    if proc.returncode == 2 or not mask_path.exists():  # noqa: PLR2004
        return None

    crop_cmd = [
        "convert",
        str(mask_path),
        "-crop",
        f"{cols}x{rows}@",
        "+repage",
        "-format",
        "%[fx:mean]\n",
        "info:",
    ]
    crop = subprocess.run(crop_cmd, check=False, capture_output=True, text=True)  # noqa: S603
    try:
        fractions = [float(value) for value in crop.stdout.split()]
    except ValueError:
        return None
    if not fractions:
        return None

    return fractions, cols, rows


def compare_images_tiled(  # noqa: PLR0913
    file1: Path, file2: Path, fuzz: str, tile_size: int, tile_cutoff_pct: float, diff_dir: Path
) -> tuple[int, str]:
    """Compare two images tile by tile, flagging if any tile differs too much.

    Args:
        file1: Path to the first image.
        file2: Path to the second image.
        fuzz: The fuzz factor (e.g. "20%").
        tile_size: Target tile edge length in pixels.
        tile_cutoff_pct: Flag the image if the worst tile's differing-pixel
            percentage exceeds this.
        diff_dir: Directory where the tile mask is written (kept on failure).

    Returns:
        A tuple of (result_code, detail). result_code is 1 if the worst tile
        exceeds the cutoff (or the images could not be compared), else 0.

    """
    mask_path = diff_dir / f"tilemask-{file1.stem}.png"
    result = get_tile_diff_fractions(file1, file2, fuzz, tile_size, mask_path)
    if result is None:
        return 1, "tiled compare failed (size mismatch?)"

    fractions, cols, rows = result
    worst = max(fractions)
    worst_pct = worst * 100.0
    row, col = divmod(fractions.index(worst), cols)
    detail = f"worst tile {worst_pct:.2f}% at (r{row},c{col}) [{cols}x{rows}]"

    if worst_pct > tile_cutoff_pct:
        return 1, detail

    if mask_path.exists():
        mask_path.unlink()
    return 0, detail


def calibrate_tiles_in_dir(  # noqa: PLR0913
    dir1: Path,
    dir2: Path,
    fuzz: str,
    tile_size: int,
    files_in_dir1: list[Path],
    diff_dir: Path | None,
) -> None:
    """Log the worst-tile differing-pixel % per image to help choose a cutoff.

    Args:
        dir1: First image directory.
        dir2: Second image directory.
        fuzz: Fuzz factor used when counting differing pixels.
        tile_size: Target tile edge length in pixels.
        files_in_dir1: The files in `dir1` to measure.
        diff_dir: Directory for the (transient) tile masks; a temp dir is used
            if None.

    """
    logger.info(f'Calibrating tile AE in "{dir1}" at fuzz {fuzz}, tile ~{tile_size}px...')
    mask_dir = diff_dir if diff_dir is not None else Path(tempfile.gettempdir())
    max_pct = 0.0
    max_name = ""
    max_pos = ""
    for image_file1 in files_in_dir1:
        image_file2 = get_image_file2(dir2, image_file1)
        if not image_file2:
            continue

        mask_path = mask_dir / f"tilemask-{image_file1.stem}.png"
        result = get_tile_diff_fractions(image_file1, image_file2, fuzz, tile_size, mask_path)
        if mask_path.exists():
            mask_path.unlink()
        if result is None:
            logger.warning(f'Could not measure tiles for "{image_file1.name}".')
            continue

        fractions, cols, rows = result
        worst = max(fractions)
        worst_pct = worst * 100.0
        row, col = divmod(fractions.index(worst), cols)
        logger.info(
            f"  {image_file1.name}: worst tile {worst_pct:.3f}% at (r{row},c{col}) [{cols}x{rows}]"
        )

        if worst_pct > max_pct:
            max_pct, max_name, max_pos = worst_pct, image_file1.name, f"(r{row},c{col})"

    if max_pct:
        logger.info(f'Max tile AE for "{dir1}": {max_pct:.3f}% {max_pos} ("{max_name}").')


def get_image_file2(dir2: Path, image_file1: Path) -> Path | None:
    image_file2 = dir2 / image_file1.name

    if not image_file2.exists():
        # Try with .jpg extension as a fallback, like in the bash script
        file2_jpg = image_file2.with_suffix(".jpg")
        if file2_jpg.exists():
            image_file2 = file2_jpg
        else:
            logger.warning(
                f"Could not find corresponding file"
                f' for "{image_file1.name}" in "{dir2}".'
                f' Tried "{image_file2.name}" and "{file2_jpg.name}".'
            )
            return None

    return image_file2


def compare_images(
    file1: Path, file2: Path, fuzz: str, ae_cutoff: float, diff_dir: Path | None
) -> tuple[int, str]:
    """Compare two images using ImageMagick's `compare` tool.

    Args:
        file1: Path to the first image.
        file2: Path to the second image.
        fuzz: The fuzz factor (e.g., "5%"). "0%" uses MAE metric.
        ae_cutoff: The pixel count cutoff for Absolute Error (AE) metric.
        diff_dir: Directory to save diff images. Required for non-zero fuzz.

    Return:
        A tuple containing the result code (0 for same, 1 for different)
        and the metric output from the `compare` command.

    """
    if fuzz == "0%":
        # Use Root Mean Squared Error (RMSE) for no-fuzz comparison
        return compare_images_rmse(file1, file2)

    # Use Absolute Error (AE) for fuzz comparison
    return compare_images_fuzz_ae(file1, file2, fuzz, ae_cutoff, diff_dir)


def compare_images_rmse(file1: Path, file2: Path, threshold: float = 0.01) -> tuple[int, str]:
    """Compare two images using ImageMagick's RMSE metric.

    Args:
        file1 (Path): Path object pointing to the first image.
        file2 (Path): Path object pointing to the second image.
        threshold (float): Maximum acceptable normalized difference (0.01 = 1%).

    Returns:
        tuple[bool, float]: A boolean indicating if it passed, and the actual RMSE value.

    """
    if not file1.exists():
        msg = f"Cannot find image: {file1}"
        raise FileNotFoundError(msg)
    if not file2.exists():
        msg = f"Cannot find image: {file2}"
        raise FileNotFoundError(msg)

    cmd = ["compare", "-metric", "RMSE", file1, file2, "null:"]

    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: PLW1510, S603

    # ImageMagick writes metric data to standard error (stderr)
    output = result.stderr.strip()

    # Exit code 2 usually means a hard error (e.g., completely different dimensions).
    if result.returncode == 2:  # noqa: PLR2004
        msg = f"ImageMagick failed to compare images: {output}"
        raise RuntimeError(msg)

    # Extract the normalized number inside the parentheses.
    match = re.search(r"\(([^)]+)\)", output)
    if not match:
        if output == "0 (0)":
            return 0, "0.0"
        msg = f"Could not parse RMSE value from output: '{output}'"
        raise ValueError(msg)

    rmse_value = float(match.group(1))
    is_pass = 0 if rmse_value <= threshold else 1

    return is_pass, f"{rmse_value:.3}"


def compare_mae(file1: Path, file2: Path) -> tuple[int, str]:
    """Compare two images using ImageMagick's `compare` with the mae metric.

    Args:
        file1: Path to the first image.
        file2: Path to the second image.

    Return:
        A tuple containing the result code (0 for same, 1 for different)
        and the metric output from the `compare` command.

    """
    # Use Mean Absolute Error (MAE) for no-fuzz comparison
    command = ["compare", "-metric", "MAE", str(file1), str(file2), "NULL:"]

    # The metric value is printed to stderr
    proc = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603
    metric_output = proc.stderr.strip()

    # The original script ignores the exit code from `compare` and parses the
    # metric to decide if images are different. We replicate that logic.
    mae_value = 0.0
    result = 0
    try:
        # MAE output is like "123.45 (0.00188)". We need the first number.
        mae_value = float(metric_output.split()[0])
        if mae_value > 1.0:
            result = 1
    except (ValueError, IndexError):
        # If output is not a number, something went wrong.
        # Treat as different, and the metric_output will show the error.
        result = 1

    if result == 1:
        logger.error(
            f'Error comparing "{file1}": {mae_value}. Compare command: {" ".join(command)}'
        )

    return result, metric_output


def compare_images_fuzz_ae(
    file1: Path, file2: Path, fuzz: str, ae_cutoff: float, diff_dir: Path | None
) -> tuple[int, str]:
    """Compare two images using ImageMagick's `compare` tool, with 'fuzz' and 'ae'.

    Args:
        file1: Path to the first image.
        file2: Path to the second image.
        fuzz: The fuzz factor (e.g., "5%"). "0%" uses MAE metric.
        ae_cutoff: The pixel count cutoff for Absolute Error (AE) metric.
        diff_dir: Directory to save diff images. Required for non-zero fuzz.

    Return:
        A tuple containing the result code (0 for same, 1 for different)
        and the metric output from the `compare` command.

    """
    # Use Absolute Error (AE) for fuzz comparison
    if not diff_dir:
        msg = "diff_dir must be provided for non-zero fuzz."
        raise ValueError(msg)

    diff_dir.mkdir(parents=True, exist_ok=True)
    diff_file = diff_dir / f"diff-{file1.name}"

    command = [
        "compare",
        "-metric",
        "AE",
        "-fuzz",
        fuzz,
        str(file1),
        str(file2),
        str(diff_file),
    ]
    proc = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603
    metric_output = proc.stderr.strip()

    result = 0
    ae_value = 0.0
    try:
        # AE output is two numbers: pixel count; normalized count
        ae_value = float(metric_output.split()[0])
        if ae_value > ae_cutoff:
            result = 1
    except (ValueError, IndexError):
        result = 1

    if result == 1:
        logger.error(f'Error comparing "{file1}": {ae_value} > {ae_cutoff}.')
        logger.error(f" Compare command: {' '.join(command)}")
    elif diff_file.exists():
        # Images are the same, no need for the diff file.
        diff_file.unlink()

    return result, metric_output


def main(
    dir1: Annotated[Path, typer.Argument(help="First directory of images.")],
    dir2: Annotated[Path, typer.Argument(help="Second directory of images.")],
    fuzz: Annotated[
        str,
        typer.Argument(
            help="Fuzz factor for comparison (e.g., '5%').\n"
            "A value of '0%' uses the MAE metric instead of AE."
        ),
    ],
    ae_cutoff: Annotated[
        float,
        typer.Argument(
            help="AE (Absolute Error) pixel count cutoff for non-zero fuzz.\n"
            "Required if fuzz is not '0%'."
        ),
    ] = 0.0,
    diff_dir: Annotated[
        Path | None,
        typer.Argument(
            help="Directory to store difference images for non-zero fuzz.\n"
            "Required if fuzz is not '0%'."
        ),
    ] = None,
) -> None:
    """Compare all images in two directories."""
    image_errors = compare_images_in_dir(dir1, dir2, fuzz, ae_cutoff, diff_dir)

    sys.exit(len(image_errors))


if __name__ == "__main__":
    typer.run(main)
