import sys
from pathlib import Path
from typing import Annotated

import typer
from barks_fantagraphics.comics_helpers import get_comic_titles
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.common_typer_options import VolumesArg
from compare_build_dirs import compare_build_dirs, print_error_summary
from compare_images import CompareError
from loguru import logger
from rich.console import Console


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


def get_volume_dirnames(volumes_str: str) -> set[str]:
    """Return the build directory names of every title in the given volumes.

    The names come from each comic book rather than its title, because a title's
    directory drops characters a title can have, such as "Fun? What's That?".

    Args:
        volumes_str: A Fanta volume list, such as "5", "5-7" or "2,4-6".

    Returns:
        The directory names, such as "319 Fun What's That".

    """
    comics_database, titles = get_comic_titles(volumes_str, "")
    return {comics_database.get_comic_book(t).get_dest_rel_dirname() for t in titles}


def get_missing_volume_dir_errors(
    dir1: Path, volume_dirnames: set[str] | None
) -> list[tuple[str, CompareError]]:
    """Return an error for each volume title with no build directory in `dir1`.

    Args:
        dir1: First build root directory.
        volume_dirnames: The directory names asked for by volume, if any.

    Returns:
        A list of (directory name, error) pairs, empty if none are missing.

    """
    if not volume_dirnames:
        return []
    return [
        (
            name,
            CompareError(
                error_type="dir-missing", file=f'"{dir1 / name}"', detail="build dir does not exist"
            ),
        )
        for name in sorted(volume_dirnames)
        if not (dir1 / name).is_dir()
    ]


def is_selected(
    subdir: Path, name_filter: str | None, title: str | None, volume_dirnames: set[str] | None
) -> bool:
    """Return True if a comic subdirectory passes the name filter, title and volumes.

    Args:
        subdir: A comic directory named "NNN Title".
        name_filter: If set, a string the directory name must contain.
        title: If set, the exact title the directory must be for.
        volume_dirnames: If set, the directory names the directory must be one of.

    Returns:
        True if the directory should be compared.

    """
    if name_filter and name_filter not in subdir.name:
        return False
    if volume_dirnames is not None and subdir.name not in volume_dirnames:
        return False
    return not title or title == subdir.name.partition(" ")[2]


def print_progress(console: Console, num: int, total: int, name: str, num_errors: int) -> None:
    """Print a one-line progress report as a comic directory's comparison starts.

    It goes to the console, not the logger, so that a run with logging turned
    off still shows what it is up to.

    Args:
        console: The console to print to.
        num: The directory's 1-based position in the run.
        total: The number of directories in the run.
        name: The directory name.
        num_errors: The number of errors found so far.

    """
    width = len(str(total))
    errors_str = f"  ({num_errors} errors so far)" if num_errors else ""
    # Titles are printed as-is: no markup, which a "[" in a title would trip up.
    console.print(f"[{num:{width}}/{total}] {name}{errors_str}", markup=False, highlight=False)


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


def main(  # noqa: PLR0913
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
    volumes_str: VolumesArg = "",
    skip_metadata: Annotated[
        bool,
        typer.Option(
            "--skip-metadata",
            help="Do not diff the non-image files (ini copy, metadata and summary files). "
            "The images and archive are still checked.",
        ),
    ] = False,
) -> None:
    """Compare two build root directories.

    First diff files (excluding images), then compare images in the 'images'
    subdirectories.
    """
    check_dirs(dir1, dir2, title)
    volume_dirnames = get_volume_dirnames(volumes_str) if volumes_str else None

    selected = [
        d for d in sorted(dir1.iterdir()) if is_selected(d, name_filter, title, volume_dirnames)
    ]

    # Progress and the outcome go straight to the console, not the logger, so that
    # they still show when the log level is raised to hide per-file detail.
    console = Console()
    all_errors = get_missing_volume_dir_errors(dir1, volume_dirnames)
    num_ignored = 0
    for num, subdir1 in enumerate(selected, start=1):
        print_progress(console, num, len(selected), subdir1.name, len(all_errors))

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
        for err in compare_build_dirs(subdir1, subdir2, skip_metadata):
            if is_ignored_image_diff(err, ignore_image_diffs):
                num_ignored += 1
            else:
                all_errors.append((subdir1.name, err))

    if ignore_image_diffs:
        console.print(
            f"Ignored {num_ignored} image differences in: {', '.join(ignore_image_diffs)}."
        )
    if all_errors:
        print_error_summary(all_errors)
        console.print(f"[red]Comparison failed with {len(all_errors)} errors.[/red]")
    else:
        console.print("[green]Comparison successful. All directories are equivalent.[/green]")

    # Exit with a plain pass/fail status: an error *count* would be truncated
    # modulo 256 by the shell, so exactly 256 errors would look like success.
    sys.exit(1 if all_errors else 0)


if __name__ == "__main__":
    typer.run(main)
