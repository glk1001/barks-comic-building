import sys
from pathlib import Path
from typing import Annotated

import typer
from barks_fantagraphics.comics_utils import get_abbrev_path
from compare_build_dirs import compare_build_dirs, print_error_summary
from compare_images import CompareError
from loguru import logger


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

    all_errors: list[tuple[str, CompareError]] = []
    for subdir1 in sorted(dir1.iterdir()):
        if name_filter and name_filter not in subdir1.name:
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
        all_errors.extend((subdir1.name, err) for err in compare_build_dirs(subdir1, subdir2))

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
