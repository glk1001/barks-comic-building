import re
import subprocess
import sys
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
        calibrate: When True, log the AE pixel count per image (at `fuzz`)
            without applying any cutoff, and return no errors.

    Returns:
        A list of comparison errors (empty in calibration mode).

    """
    _validate_compare_inputs(
        dir1, dir2, fuzz, ae_cutoff, ae_cutoff_pct, diff_dir, calibrate=calibrate
    )

    files_in_dir1 = sorted(f for f in dir1.iterdir() if f.is_file())

    if calibrate:
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
            image_file1, image_file2, fuzz, ae_cutoff, ae_cutoff_pct, diff_dir
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
) -> CompareError | None:
    """Compare a single image pair, returning a CompareError if they differ.

    When `ae_cutoff_pct` is given, the cutoff is derived from the first image's
    total pixel count; otherwise the absolute `ae_cutoff` is used.

    Returns:
        A CompareError if the images differ beyond the cutoff, else None.

    """
    cutoff = ae_cutoff
    if ae_cutoff_pct is not None:
        total_pixels = get_pixel_count(image_file1)
        cutoff = ae_cutoff_pct / 100.0 * total_pixels if total_pixels else ae_cutoff

    logger.info(f'Comparing "{image_file1.name}"...')
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


def get_pixel_count(image: Path) -> int:
    """Return the total pixel count (width * height) of an image.

    Args:
        image: Path to the image.

    Returns:
        The pixel count, or 0 if it could not be determined.

    """
    command = ["identify", "-format", "%w %h", str(image)]
    proc = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603
    try:
        width, height = proc.stdout.split()[:2]
        return int(width) * int(height)
    except (ValueError, IndexError):
        return 0


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
