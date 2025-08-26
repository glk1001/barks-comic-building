# ruff: noqa: T201

import argparse
import sys
from pathlib import Path

from compare_build_dirs import compare_build_dirs

if __name__ == "__main__":
    """Compares two build root directories: first by diffing files (excluding images),
    then by comparing images in the 'images' subdirectories.
    """

    parser = argparse.ArgumentParser(description="Compare two build root directories.")
    parser.add_argument("dir1", type=Path, help="First build directory.")
    parser.add_argument("dir2", type=Path, help="Second build directory.")
    args = parser.parse_args()

    if not args.dir1.is_dir():
        raise FileNotFoundError(f'Error: Could not find build directory1: "{args.dir1}".')
    if not args.dir2.is_dir():
        raise FileNotFoundError(f'Error: Could not find build directory2: "{args.dir2}".')

    num_errors = 0
    for file in args.dir1.iterdir():
        if not file.is_dir():
            raise FileExistsError(f'Error: Expecting dir not file: "{file}".')

        subdir1 = file
        subdir2 = args.dir2 / file.name
        num_errors += compare_build_dirs(subdir1, subdir2)

    if num_errors > 0:
        print(f"\nComparison failed with {num_errors} errors.")
    else:
        print("\nComparison successful. All directories are equivalent.")

    sys.exit(num_errors)
