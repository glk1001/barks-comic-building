import argparse
import subprocess
import sys
from pathlib import Path

from loguru import logger


def compare_images_in_dir(
    dir1: Path, dir2: Path, fuzz: str, ae_cutoff: float, diff_dir: Path | None
) -> int:
    # --- Argument Validation ---
    if not dir1.is_dir():
        msg = f'Error: Could not find directory1: "{dir1}".'
        raise FileNotFoundError(msg)
    if not dir2.is_dir():
        msg = f'Error: Could not find directory2: "{dir2}".'
        raise FileNotFoundError(msg)
    if not fuzz.endswith("%"):
        msg = f"Error: The fuzz amount must end with a '%': \"{fuzz}\"."
        raise ValueError(msg)

    if fuzz != "0%":
        if not diff_dir:
            msg = f'Error: For non-zero fuzz amount "{fuzz}" you must specify a diff dir.'
            raise ValueError(msg)
        if ae_cutoff <= 0.0001:  # noqa: PLR2004
            msg = 'Error: You must specify a non-zero "AE_CUTOFF" for non-zero fuzz.'
            raise ValueError(msg)

    errors = 0
    files_in_dir1 = sorted(f for f in dir1.iterdir() if f.is_file())

    for image_file1 in files_in_dir1:
        image_file2 = get_image_file2(dir2, image_file1)
        if not image_file2:
            continue

        logger.info(f'Comparing "{image_file1.name}"...')
        result_code, metric = compare_images(image_file1, image_file2, fuzz, ae_cutoff, diff_dir)

        if result_code != 0:
            errors += 1

    return errors


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
        # Use Mean Absolute Error (MAE) for no-fuzz comparison
        return mae_compare(file1, file2)

    # Use Absolute Error (AE) for fuzz comparison
    return fuzz_ae_compare(file1, file2, fuzz, ae_cutoff, diff_dir)


def mae_compare(file1: Path, file2: Path) -> tuple[int, str]:
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


def fuzz_ae_compare(
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare all images in two directories.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("dir1", type=Path, help="First directory of images.")
    parser.add_argument("dir2", type=Path, help="Second directory of images.")
    parser.add_argument(
        "fuzz",
        type=str,
        help="Fuzz factor for comparison (e.g., '5%%').\n"
        "A value of '0%%' uses the MAE metric instead of AE.",
    )
    parser.add_argument(
        "ae_cutoff",
        type=float,
        nargs="?",
        default=0.0,
        help="AE (Absolute Error) pixel count cutoff for non-zero fuzz.\n"
        "Required if fuzz is not '0%%'.",
    )
    parser.add_argument(
        "diff_dir",
        type=Path,
        nargs="?",
        help="Directory to store difference images for non-zero fuzz.\n"
        "Required if fuzz is not '0%%'.",
    )

    args = parser.parse_args()

    the_diff_dir = None if not args.diff_dir else Path(args.diff_dir)

    num_errors = compare_images_in_dir(
        Path(args.dir1), Path(args.dir2), args.fuzz, args.ae_cutoff, the_diff_dir
    )

    # if num_errors > 0:
    #     print(f'"{args.dir1}": Found {num_errors} differing images.')  # noqa: ERA001

    sys.exit(num_errors)
