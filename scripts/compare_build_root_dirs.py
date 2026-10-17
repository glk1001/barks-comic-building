import sys
from pathlib import Path
from typing import Annotated

import typer
from barks_fantagraphics.comics_utils import get_abbrev_path
from compare_build_dirs import compare_build_dirs, print_error_summary
from compare_images import CompareError
from loguru import logger


def check_dirs(dir1: Path, dir2: Path, title: str | None) -> None:
    """Check both build root directories exist, and hold the title if one is given.

    Args:
        dir1: First build root directory.
        dir2: Second build root directory.
        title: If set, a title that must have a directory in `dir1`.

    Raises:
        FileNotFoundError: If a directory or the title's directory is missing.

    """
    if not dir1.is_dir():
        msg = f'Error: Could not find build directory1: "{dir1}".'
        raise FileNotFoundError(msg)
    if not dir2.is_dir():
        msg = f'Error: Could not find build directory2: "{dir2}".'
        raise FileNotFoundError(msg)
    # A mistyped title would otherwise compare nothing and report success.
    if title and not any(title == d.name.partition(" ")[2] for d in dir1.iterdir()):
        msg = f'Error: No title "{title}" in build directory1: "{dir1}".'
        raise FileNotFoundError(msg)


def is_selected(subdir: Path, name_filter: str | None, title: str | None) -> bool:
    """Return True if a comic subdirectory passes the name filter and title.

    Args:
        subdir: A comic directory named "NNN Title".
        name_filter: If set, a string the directory name must contain.
        title: If set, the exact title the directory must be for.

    Returns:
        True if the directory should be compared.

    """
    if name_filter and name_filter not in subdir.name:
        return False
    return not title or title == subdir.name.partition(" ")[2]


def is_ignored_image_diff(err: CompareError, ignore_image_diffs: list[str] | None) -> bool:
    """Return True if an error is a pixel difference in an image named to be ignored.

    Only "image" errors qualify, so a missing or extra copy of an ignored image
    still fails the comparison.

    Args:
        err: A comparison error from `compare_build_dirs`.
        ignore_image_diffs: Image file names whose pixel differences are ignored.

    Returns:
        True if the error should be dropped.

    """
    if not ignore_image_diffs or err.error_type != "image":
        return False
    # An "image" error's file is the quoted pair of compared paths, one per line.
    image_file1 = err.file.split("\n", 1)[0].strip('"')
    return Path(image_file1).name in ignore_image_diffs


def main(
    dir1: Annotated[Path, typer.Argument(help="First build directory.")],
    dir2: Annotated[Path, typer.Argument(help="Second build directory.")],
    name_filter: Annotated[
        str | None,
        typer.Option(
            "--filter",
            "-f",
            help="Only compare subdirectories whose name contains this string "
            "(e.g. a title or volume number).",
        ),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            "-t",
            help="Only compare the subdirectory for exactly this title, ignoring its "
            "'NNN ' chronological prefix.",
        ),
    ] = None,
    ignore_image_diffs: Annotated[
        list[str] | None,
        typer.Option(
            "--ignore-image-diff",
            "-i",
            help="Ignore pixel differences in images with this file name (e.g. 1-01.jpg). "
            "A missing or extra image is still an error. Can be repeated.",
        ),
    ] = None,
) -> None:
    """Compare two build root directories.

    First diff files (excluding images), then compare images in the 'images'
    subdirectories.
    """
    check_dirs(dir1, dir2, title)

    all_errors: list[tuple[str, CompareError]] = []
    num_ignored = 0
    for subdir1 in sorted(dir1.iterdir()):
        if not is_selected(subdir1, name_filter, title):
            continue

        if not subdir1.is_dir():
            # A stray file among the comic dirs is worth reporting, but it must
            # not abort the comparison of every comic after it.
            logger.error(f'Error: Expecting dir not file: "{subdir1}".')
            all_errors.append(
                (
                    subdir1.name,
                    CompareError(
                        error_type="not-a-dir", file=f'"{subdir1}"', detail="expecting dir not file"
                    ),
                )
            )
            continue

        subdir2 = dir2 / subdir1.name
        logger.info(f'Comparing "{get_abbrev_path(subdir1)}" to "{get_abbrev_path(subdir2)}".')
        for err in compare_build_dirs(subdir1, subdir2):
            if is_ignored_image_diff(err, ignore_image_diffs):
                num_ignored += 1
            else:
                all_errors.append((subdir1.name, err))

    if ignore_image_diffs:
        logger.warning(
            f"Ignored {num_ignored} image differences in: {', '.join(ignore_image_diffs)}."
        )
    if all_errors:
        logger.error(f"Comparison failed with {len(all_errors)} errors.")
        print_error_summary(all_errors)
    else:
        logger.success("Comparison successful. All directories are equivalent.")

    # Exit with a plain pass/fail status: an error *count* would be truncated
    # modulo 256 by the shell, so exactly 256 errors would look like success.
    sys.exit(1 if all_errors else 0)


if __name__ == "__main__":
    typer.run(main)
