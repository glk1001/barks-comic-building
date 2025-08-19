# ruff: noqa: T201

import argparse
import sys
from pathlib import Path

from compare_images import compare_images_in_dir
from intspan import intspan

if __name__ == "__main__":
    """Compares the images in two Fantagraphics directories.
    """

    parser = argparse.ArgumentParser(description="Compare two Fantagraphics directories.")
    parser.add_argument("dir1", type=Path, help="First directory.")
    parser.add_argument("dir2", type=Path, help="Second directory.")
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
    parser.add_argument(
        "volume",
        type=str,
        nargs="?",
        help="Volume to compare.",
    )

    args = parser.parse_args()

    volumes = list(intspan(args.volume))
    print(volumes)

    if not args.dir1.is_dir():
        raise FileNotFoundError(f'Error: Could not find Fantagraphics directory1: "{args.dir1}".')
    if not args.dir2.is_dir():
        raise FileNotFoundError(f'Error: Could not find Fantagraphics directory2: "{args.dir2}".')

    num_errors = 0
    for file1 in args.dir1.iterdir():
        if not file1.is_dir():
            raise FileExistsError(f'Error: Expecting dir not file: "{file1}".')

        if not any(str(v) in str(file1.name) for v in volumes):
            continue

        print(f'\nComparing image dirs in {file1.name}"...')

        image_dir1 = file1 / "images"
        image_dir2 = args.dir2 / file1.name / "images"
        diff_dir = args.diff_dir / file1.name

        num_errors += compare_images_in_dir(
            image_dir1, image_dir2, args.fuzz, args.ae_cutoff, diff_dir
        )

    if num_errors > 0:
        print(f"\nComparison failed with {num_errors} errors.")
    else:
        print("\nComparison successful. Directories are equivalent.")

    sys.exit(num_errors)
