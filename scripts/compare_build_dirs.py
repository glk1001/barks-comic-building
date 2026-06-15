import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from compare_images import CompareError, compare_images_in_dir
from loguru import logger


def compare_build_dirs(dir1: Path, dir2: Path) -> list[CompareError]:
    logger.info(f'Comparing "{dir1}" to "{dir2}"...')

    if not dir1.is_dir():
        msg = f'Error: Could not find build directory1: "{dir1}".'
        raise FileNotFoundError(msg)
    if not dir2.is_dir():
        msg = f'Error: Could not find build directory2: "{dir2}".'
        raise FileNotFoundError(msg)

    errs = compare_dirs_excluding_images(dir1, dir2)
    errs += compare_dir_images(dir1, dir2)

    return errs


def compare_dirs_excluding_images(dir1: Path, dir2: Path) -> list[CompareError]:
    errs: list[CompareError] = []
    logger.info(f"\nComparing non-image files in '{dir1}' to '{dir2}'...")

    diff_command = [
        "diff",
        "-r",
        "--exclude=images",
        "-I",
        "time of run",
        "-I",
        "time taken",
        "-I",
        "Created:",
        "-I",
        "timestamp",
        "-I",
        "ini file",
        "-I",
        "title font file",
        "-I",
        "ini_hash",  # TODO(glk1001): Temporary until all built comics use metadata
        str(dir1),
        str(dir2),
    ]

    proc = subprocess.run(diff_command, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        logger.error(f"Error: Some files differ between '{dir1}' and '{dir2}'.")
        logger.error("--- diff output ---")
        logger.error(proc.stdout)
        if proc.stderr:
            logger.error("--- diff stderr ---")
            logger.error(proc.stderr)
        logger.error("-------------------")
        errs = parse_diff_output(proc.stdout)
        if not errs:
            # The files differ but the output did not name any (e.g. a stderr-only
            # failure). Record a single generic error so it is still reported.
            errs = [CompareError(error_type="file-diff", file=str(dir1), detail="files differ")]

    return errs


def parse_diff_output(diff_output: str) -> list[CompareError]:
    """Extract per-file errors from the output of `diff -r`.

    Args:
        diff_output: The stdout captured from a recursive `diff` run.

    Returns:
        A list of errors, one per differing or missing file named in the output.

    """
    errs: list[CompareError] = []
    for line in diff_output.splitlines():
        if line.startswith("Files ") and line.endswith(" differ"):
            # Lines of the form: Files <path1> and <path2> differ
            inner = line[len("Files ") : -len(" differ")]
            file = inner.split(" and ", 1)[0]
            errs.append(CompareError(error_type="file-diff", file=file, detail="contents differ"))
        elif line.startswith("Only in "):
            # Lines of the form: Only in <dir>: <name>
            location, _, name = line[len("Only in ") :].partition(": ")
            file = str(Path(location) / name)
            errs.append(
                CompareError(error_type="file-missing", file=file, detail="only in one dir")
            )

    return errs


def compare_dir_images(dir1: Path, dir2: Path) -> list[CompareError]:
    dir1_images = dir1 / "images"
    dir2_images = dir2 / "images"

    if not dir1_images.is_dir():
        msg = f'Could not find images dir "{dir1_images}"'
        raise FileNotFoundError(msg)

    if not dir2_images.is_dir():
        msg = f'Could not find images dir "{dir2_images}"'
        raise FileNotFoundError(msg)

    logger.info(f"Comparing images in '{dir1_images}' to '{dir2_images}'...")
    compare_fuzz = "0%"
    try:
        # For 0% fuzz, ae_cutoff and diff_dir are not used.
        image_errors = compare_images_in_dir(
            dir1_images, dir2_images, fuzz=compare_fuzz, ae_cutoff=0.0, diff_dir=None
        )
        if image_errors:
            logger.error(f"Error: Found {len(image_errors)} different images.")
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"Error during image comparison: {e}")
        return [CompareError(error_type="image-error", file=str(dir1_images), detail=str(e))]

    return image_errors


def main(
    dir1: Annotated[Path, typer.Argument(help="First build directory.")],
    dir2: Annotated[Path, typer.Argument(help="Second build directory.")],
) -> None:
    """Compare two build directories.

    First diff files (excluding images), then compare images in the 'images'
    subdirectories.
    """
    errors = compare_build_dirs(dir1, dir2)

    if errors:
        logger.error(f"\nComparison failed with {len(errors)} errors.")
    else:
        logger.success("\nComparison successful. Directories are equivalent.")

    sys.exit(len(errors))


if __name__ == "__main__":
    typer.run(main)
