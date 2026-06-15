import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from compare_images import CompareError, compare_images_in_dir
from loguru import logger
from rich.console import Console
from rich.table import Table

# Lines that legitimately differ between otherwise-equivalent builds and so must
# be ignored when diffing non-image files.
DIFF_IGNORE_OPTIONS = [
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
]

# Number of diff lines shown inline in the summary table before truncating.
_MAX_DIFF_PREVIEW_LINES = 4


def print_error_summary(errors: list[tuple[str, CompareError]]) -> None:
    """Print a rich summary table of all comparison errors.

    Any errors carrying full context (e.g. a complete file diff) have that
    context logged below the table.

    Args:
        errors: A list of (directory name, error) pairs collected over all
            compared directories.

    """
    table = Table(title="Comparison Errors", show_lines=True)
    table.add_column("Directory", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta", no_wrap=True)
    table.add_column("File", style="yellow")
    table.add_column("Detail", style="white")

    for dir_name, err in errors:
        table.add_row(dir_name, err.error_type, err.file, err.detail)

    Console().print(table)

    for dir_name, err in errors:
        if err.context:
            files = err.file.replace("\n", " vs ")
            logger.info(f'\nFull diff for "{dir_name}" file {files}:\n{err.context}')


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
    logger.info(f'\nComparing non-image files in "{dir1}" to "{dir2}"...')

    # Use brief mode (`-q`) so that every differing file -- text or binary -- is
    # reported uniformly as "Files <a> and <b> differ", which we can parse per file.
    diff_command = [
        "diff",
        "-r",
        "-q",
        "--exclude=images",
        *DIFF_IGNORE_OPTIONS,
        str(dir1),
        str(dir2),
    ]

    proc = subprocess.run(diff_command, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode == 0:
        return []

    logger.error(f'Error: Some files differ between "{dir1}" and "{dir2}".')
    if proc.stderr:
        logger.error(f"--- diff stderr ---\n{proc.stderr}")

    errs = parse_diff_output(proc.stdout)
    if not errs:
        # The files differ but the output did not name any (e.g. a stderr-only
        # failure). Record a single generic error so it is still reported.
        errs = [CompareError(error_type="file-diff", file=str(dir1), detail="files differ")]

    return errs


def parse_diff_output(diff_output: str) -> list[CompareError]:
    """Extract per-file errors from the output of `diff -rq`.

    For each differing file the full diff is captured (and truncated for the
    summary table) so the caller has the changed lines for context.

    Args:
        diff_output: The stdout captured from a recursive brief `diff` run.

    Returns:
        A list of errors, one per differing or missing file named in the output.

    """
    errs: list[CompareError] = []
    for line in diff_output.splitlines():
        if line.startswith("Files ") and line.endswith(" differ"):
            # Lines of the form: Files <path1> and <path2> differ
            inner = line[len("Files ") : -len(" differ")]
            file1_str, _, file2_str = inner.partition(" and ")
            file1_str = file1_str.strip("'")
            file2_str = file2_str.strip("'")
            full_diff = get_file_diff(Path(file1_str), Path(file2_str))
            errs.append(
                CompareError(
                    error_type="file-diff",
                    file=f'"{file1_str}"\n"{file2_str}"',
                    detail=_truncate_diff(full_diff),
                    context=full_diff,
                )
            )
        elif line.startswith("Only in "):
            # Lines of the form: Only in <dir>: <name>
            location, _, name = line[len("Only in ") :].partition(": ")
            file = str(Path(location) / name)
            errs.append(
                CompareError(error_type="file-missing", file=file, detail="only in one dir")
            )

    return errs


def get_file_diff(file1: Path, file2: Path) -> str:
    """Return the textual diff between two files, ignoring volatile lines.

    Args:
        file1: Path to the first file.
        file2: Path to the second file.

    Returns:
        The diff output, or an empty string if the files do not differ once
        volatile lines are ignored.

    """
    command = ["diff", *DIFF_IGNORE_OPTIONS, str(file1), str(file2)]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    return proc.stdout.strip()


def _truncate_diff(diff_text: str, max_lines: int = _MAX_DIFF_PREVIEW_LINES) -> str:
    """Return the first few lines of a diff for inline display.

    Args:
        diff_text: The full diff text.
        max_lines: Maximum number of lines to keep before adding an ellipsis.

    Returns:
        A short preview of the diff, or a generic message if it is empty.

    """
    if not diff_text:
        return "contents differ"

    lines = diff_text.splitlines()
    if len(lines) <= max_lines:
        return diff_text

    return "\n".join(lines[:max_lines]) + "\n…"


def compare_dir_images(dir1: Path, dir2: Path) -> list[CompareError]:
    dir1_images = dir1 / "images"
    dir2_images = dir2 / "images"

    if not dir1_images.is_dir():
        msg = f'Could not find images dir "{dir1_images}"'
        raise FileNotFoundError(msg)

    if not dir2_images.is_dir():
        msg = f'Could not find images dir "{dir2_images}"'
        raise FileNotFoundError(msg)

    logger.info(f'Comparing images in "{dir1_images}" to "{dir2_images}"...')
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
        print_error_summary([(dir1.name, err) for err in errors])
    else:
        logger.success("\nComparison successful. Directories are equivalent.")

    sys.exit(len(errors))


if __name__ == "__main__":
    typer.run(main)
