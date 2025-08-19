# ruff: noqa: T201

import argparse
import subprocess
import sys
from pathlib import Path

from compare_images import compare_images_in_dir


def compare_build_dirs(dir1: Path, dir2: Path) -> int:
    if not dir1.is_dir():
        raise FileNotFoundError(f'Error: Could not find build directory1: "{dir1}".')
    if not dir2.is_dir():
        raise FileNotFoundError(f'Error: Could not find build directory2: "{dir2}".')

    errs = compare_dirs_excluding_images(dir1, dir2)
    errs += compare_dir_images(dir1, dir2)

    return errs


def compare_dirs_excluding_images(dir1: Path, dir2: Path) -> int:
    errs = 0
    print(f"\nComparing contents of '{dir1}' and '{dir2}'...")

    diff_command = [
        "diff",
        "-r",
        "--exclude=images",
        "-I",
        "ini file",
        "-I",
        "time of run",
        "-I",
        "time taken",
        "-I",
        "Created:",
        "-I",
        "timestamp",
        str(dir1),
        str(dir2),
    ]

    proc = subprocess.run(diff_command, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f"Error: Files differ between '{dir1}' and '{dir2}'.")
        print("--- diff output ---")
        print(proc.stdout)
        if proc.stderr:
            print("--- diff stderr ---")
            print(proc.stderr)
        print("-------------------")
        errs = 1

    return errs


def compare_dir_images(dir1: Path, dir2: Path) -> int:
    dir1_images = dir1 / "images"
    dir2_images = dir2 / "images"

    if not dir1_images.is_dir():
        raise FileNotFoundError(f'Could not find images dir "{dir1_images}"')

    if not dir2_images.is_dir():
        raise FileNotFoundError(f'Could not find images dir "{dir2_images}"')

    print(f"Comparing images in '{dir1_images}' and '{dir2_images}'...")
    compare_fuzz = "0%"
    errs = 0
    try:
        # For 0% fuzz, ae_cutoff and diff_dir are not used.
        image_errors = compare_images_in_dir(
            dir1_images, dir2_images, fuzz=compare_fuzz, ae_cutoff=0.0, diff_dir=None
        )
        if image_errors > 0:
            print(f"Error: Found {image_errors} different images.")
            errs += image_errors
    except (FileNotFoundError, ValueError) as e:
        print(f"Error during image comparison: {e}")
        errs = 1

    return errs


if __name__ == "__main__":
    """Compares two build directories: first by diffing files (excluding images),
    then by comparing images in the 'images' subdirectories.
    """
    parser = argparse.ArgumentParser(description="Compare two build output directories.")
    parser.add_argument("dir1", type=Path, help="First build directory.")
    parser.add_argument("dir2", type=Path, help="Second build directory.")
    args = parser.parse_args()

    errors = compare_build_dirs(args.dir1, args.dir2)

    if errors > 0:
        print(f"\nComparison failed with {errors} categories of errors.")
    else:
        print("\nComparison successful. Directories are equivalent.")

    sys.exit(errors)
