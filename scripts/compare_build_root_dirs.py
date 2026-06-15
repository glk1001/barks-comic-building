import sys
from pathlib import Path
from typing import Annotated

import typer
from barks_fantagraphics.comics_utils import get_abbrev_path
from compare_build_dirs import compare_build_dirs
from compare_images import CompareError
from loguru import logger
from rich.console import Console
from rich.table import Table


def print_error_summary(errors: list[tuple[str, CompareError]]) -> None:
    """Print a rich summary table of all comparison errors.

    Args:
        errors: A list of (directory name, error) pairs collected over all
            compared subdirectories.

    """
    table = Table(title="Comparison Errors", show_lines=False)
    table.add_column("Directory", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta", no_wrap=True)
    table.add_column("File", style="yellow")
    table.add_column("Detail", style="white")

    for dir_name, err in errors:
        table.add_row(dir_name, err.error_type, err.file, err.detail)

    Console().print(table)


def main(
    dir1: Annotated[Path, typer.Argument(help="First build directory.")],
    dir2: Annotated[Path, typer.Argument(help="Second build directory.")],
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

        subdir2 = dir2 / subdir1.name
        logger.info(f'Comparing "{get_abbrev_path(subdir1)}" to "{get_abbrev_path(subdir2)}".')
        all_errors.extend((subdir1.name, err) for err in compare_build_dirs(subdir1, subdir2))

    if all_errors:
        logger.error(f"\nComparison failed with {len(all_errors)} errors.")
        print_error_summary(all_errors)
    else:
        logger.info("\nComparison successful. All directories are equivalent.")

    sys.exit(len(all_errors))


if __name__ == "__main__":
    typer.run(main)
