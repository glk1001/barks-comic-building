import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from barks_fantagraphics.comics_utils import get_abbrev_path
from compare_build_dirs import compare_build_dirs, print_error_summary
from loguru import logger

if TYPE_CHECKING:
    from compare_images import CompareError


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
) -> None:
    """Compare two build root directories.

    First diff files (excluding images), then compare images in the 'images'
    subdirectories.
    """
    if not dir1.is_dir():
        msg = f'Error: Could not find build directory1: "{dir1}".'
        raise FileNotFoundError(msg)
    if not dir2.is_dir():
        msg = f'Error: Could not find build directory2: "{dir2}".'
        raise FileNotFoundError(msg)

    dirs = sorted([Path(d) for d in dir1.iterdir()])
    assert dirs is not None

    all_errors: list[tuple[str, CompareError]] = []
    for subdir1 in dirs:
        if not subdir1.is_dir():
            msg = f'Error: Expecting dir not file: "{subdir1}".'
            raise FileExistsError(msg)

        if name_filter and name_filter not in subdir1.name:
            continue

        subdir2 = dir2 / subdir1.name
        logger.info(f'Comparing "{get_abbrev_path(subdir1)}" to "{get_abbrev_path(subdir2)}".')
        all_errors.extend((subdir1.name, err) for err in compare_build_dirs(subdir1, subdir2))

    if all_errors:
        logger.error(f"Comparison failed with {len(all_errors)} errors.")
        print_error_summary(all_errors)
    else:
        logger.success("Comparison successful. All directories are equivalent.")

    sys.exit(len(all_errors))


if __name__ == "__main__":
    typer.run(main)
