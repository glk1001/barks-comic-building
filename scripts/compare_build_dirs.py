import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Annotated

import typer
from barks_build_comic_images.consts import SUMMARY_FILENAME
from compare_images import CompareError, compare_images_in_dir
from loguru import logger
from rich.console import Console
from rich.table import Table

# The build writes the summary file into the build dir but deliberately leaves
# it out of the cbz archive, so it must not count as a missing archive member.
ARCHIVE_EXCLUDED_FILES = frozenset({SUMMARY_FILENAME})

# Keys in the summary file holding the paths the build wrote outside the build
# dir. The paths are stored with the home dir replaced by "$HOME".
ZIP_KEY = "dest comic_zip"
SERIES_SYMLINK_KEY = "dest series zip symlink"
YEAR_SYMLINK_KEY = "dest year zip symlink"
SUMMARY_PATH_KEYS = (ZIP_KEY, SERIES_SYMLINK_KEY, YEAR_SYMLINK_KEY)

# Lines that legitimately differ between otherwise-equivalent builds and so must
# be ignored when diffing non-image files.
#
# The two path lines ("ini file", "title font file") are ignored because a
# regression baseline may have been built from a checkout at a different
# location. Note that this hides only where the ini came from, not what was in
# it: `ini_hash` in comic-metadata.json is deliberately NOT ignored, so a build
# made from different ini *content* still fails the comparison.
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
]


def print_error_summary(errors: list[tuple[str, CompareError]]) -> None:
    """Print a rich summary table of all comparison errors.

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


def compare_build_dirs(dir1: Path, dir2: Path) -> list[CompareError]:
    """Compare one built comic directory to another.

    A missing directory is returned as an error rather than raised, so that a
    caller comparing many comics reports it and carries on instead of aborting
    the whole run on the first title that failed to build.

    Args:
        dir1: The reference (baseline) build directory.
        dir2: The build directory under test.

    Returns:
        A list of comparison errors, empty if the two builds are equivalent.

    """
    logger.info(f'Comparing "{dir1}" to "{dir2}"...')

    missing = [
        CompareError(error_type="dir-missing", file=f'"{d}"', detail="build dir does not exist")
        for d in (dir1, dir2)
        if not d.is_dir()
    ]
    if missing:
        for err in missing:
            logger.error(f"Error: Could not find build directory: {err.file}.")
        return missing

    errs = compare_dirs_excluding_images(dir1, dir2)
    errs += compare_dir_images(dir1, dir2)
    errs += check_comic_archive(dir2)

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
        errs = [CompareError(error_type="file", file=str(dir1), detail="files differ")]

    return errs


def parse_diff_output(diff_output: str) -> list[CompareError]:
    """Extract per-file errors from the output of `diff -rq`.

    For each differing file the full diff is logged inline (so it appears in the
    scrollback near where it was found); the table only flags the file with a
    short "diff" marker, keeping rows short and the paths easy to copy.

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
            if full_diff:
                logger.error(f'Diff for "{file1_str}" vs "{file2_str}":\n{full_diff}')
            errs.append(
                CompareError(
                    error_type="file",
                    file=f'"{file1_str}"\n"{file2_str}"',
                    detail="diff",
                )
            )
        elif line.startswith("Only in "):
            # Lines of the form: Only in <dir>: <name>
            location, _, name = line[len("Only in ") :].partition(": ")
            file = Path(location) / name
            errs.append(
                CompareError(error_type="file-missing", file=f'"{file}"', detail="only in one dir")
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


def compare_dir_images(dir1: Path, dir2: Path) -> list[CompareError]:
    dir1_images = dir1 / "images"
    dir2_images = dir2 / "images"

    missing = [
        CompareError(error_type="dir-missing", file=f'"{d}"', detail="images dir does not exist")
        for d in (dir1_images, dir2_images)
        if not d.is_dir()
    ]
    if missing:
        for err in missing:
            logger.error(f"Error: Could not find images dir: {err.file}.")
        return missing

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


def check_comic_archive(build_dir: Path) -> list[CompareError]:
    """Check the cbz archive and symlinks a build wrote outside its build dir.

    The build dirs are only half of what a build produces; the archive and its
    two symlinks are the half the reader actually consumes. There is no baseline
    to diff them against, so they are checked for self-consistency instead: the
    archive must hold exactly the build dir's files, must not predate them, and
    both symlinks must resolve to it.

    Args:
        build_dir: The build directory whose archive should be checked.

    Returns:
        A list of errors, empty if the archive and symlinks are consistent.

    """
    summary_file = build_dir / SUMMARY_FILENAME
    if not summary_file.is_file():
        return [
            CompareError(
                error_type="archive-unchecked",
                file=f'"{summary_file}"',
                detail="no summary file, cannot locate the archive",
            )
        ]

    logger.info(f'Checking the archive built from "{build_dir}"...')
    paths = get_summary_paths(summary_file)

    errs = [
        CompareError(
            error_type="archive-unchecked",
            file=f'"{summary_file}"',
            detail=f'summary has no "{key}" line',
        )
        for key in SUMMARY_PATH_KEYS
        if key not in paths
    ]
    if ZIP_KEY not in paths:
        return errs

    zip_path = paths[ZIP_KEY]
    if not zip_path.is_file():
        errs.append(
            CompareError(
                error_type="archive-missing", file=f'"{zip_path}"', detail="archive does not exist"
            )
        )
        return errs

    errs += compare_archive_contents(build_dir, zip_path)
    errs += [
        err
        for key in (SERIES_SYMLINK_KEY, YEAR_SYMLINK_KEY)
        if key in paths
        for err in check_zip_symlink(paths[key], zip_path)
    ]

    return errs


def get_summary_paths(summary_file: Path) -> dict[str, Path]:
    """Read the build-output paths recorded in a summary file.

    Only the `SUMMARY_PATH_KEYS` lines are extracted. Each is stored as
    `key = "<path>"` with the home dir written as "$HOME", which is expanded
    back so the result can be used directly.

    Args:
        summary_file: The build's summary file.

    Returns:
        A mapping of summary key to the path it records, omitting any key the
        summary file does not have.

    """
    paths: dict[str, Path] = {}
    for line in summary_file.read_text().splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if key in SUMMARY_PATH_KEYS:
            paths[key] = Path(value.strip().strip('"').replace("$HOME", str(Path.home())))

    return paths


def compare_archive_contents(build_dir: Path, zip_path: Path) -> list[CompareError]:
    """Check a cbz archive holds exactly its build dir's files, and is no older.

    Args:
        build_dir: The build directory the archive was made from.
        zip_path: The cbz archive to check.

    Returns:
        A list of errors, empty if the archive matches the build dir.

    """
    build_files = {
        p.relative_to(build_dir).as_posix(): p
        for p in build_dir.rglob("*")
        if p.is_file() and p.name not in ARCHIVE_EXCLUDED_FILES
    }

    try:
        with zipfile.ZipFile(zip_path) as archive:
            archived = {info.filename for info in archive.infolist() if not info.is_dir()}
    except (OSError, zipfile.BadZipFile) as e:
        logger.error(f'Error reading archive "{zip_path}": {e}')
        return [CompareError(error_type="archive-error", file=f'"{zip_path}"', detail=str(e))]

    errs = [
        CompareError(error_type="archive-missing", file=f'"{zip_path}"', detail=f'missing "{name}"')
        for name in sorted(set(build_files) - archived)
    ]
    errs += [
        CompareError(
            error_type="archive-extra", file=f'"{zip_path}"', detail=f'unexpected "{name}"'
        )
        for name in sorted(archived - set(build_files))
    ]

    # The archive is written after the files it holds, so anything newer than it
    # means the build dir was updated without the archive being rebuilt.
    newest = max((p.stat().st_mtime for p in build_files.values()), default=0.0)
    if zip_path.stat().st_mtime < newest:
        errs.append(
            CompareError(
                error_type="archive-stale",
                file=f'"{zip_path}"',
                detail="archive is older than the build dir it holds",
            )
        )

    return errs


def check_zip_symlink(link: Path, zip_path: Path) -> list[CompareError]:
    """Check a symlink exists and resolves to the given archive.

    Args:
        link: The symlink the build should have written.
        zip_path: The archive it is expected to point at.

    Returns:
        A list of errors, empty if the symlink points at `zip_path`.

    """
    if not link.is_symlink():
        detail = "exists but is not a symlink" if link.exists() else "symlink does not exist"
        logger.error(f'Error: Bad comic zip symlink "{link}": {detail}.')
        return [CompareError(error_type="symlink-missing", file=f'"{link}"', detail=detail)]

    target = link.resolve()
    if target != zip_path.resolve():
        logger.error(f'Error: Symlink "{link}" points to "{target}", not "{zip_path}".')
        return [
            CompareError(
                error_type="symlink-wrong", file=f'"{link}"', detail=f'points to "{target}"'
            )
        ]

    return []


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
        logger.error(f"Comparison failed with {len(errors)} errors.")
        print_error_summary([(dir1.name, err) for err in errors])
    else:
        logger.success("Comparison successful. Directories are equivalent.")

    # Exit with a plain pass/fail status: an error *count* would be truncated
    # modulo 256 by the shell, so exactly 256 errors would look like success.
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    typer.run(main)
