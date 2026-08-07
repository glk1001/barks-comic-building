import shutil
import sys
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from barks_fantagraphics.comic_book import ComicBook, ModifiedType
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_helpers import get_comic_titles
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comic_utils.pil_image_utils import downscale_png, load_pil_image_for_reading
from compare_images import (
    CalibrationResult,
    CompareError,
    compare_image_lists,
    log_calibration_summary,
)
from loguru import logger
from loguru_config import LoguruConfig
from rich.console import Console
from rich.table import Table

APP_LOGGING_NAME = "fcmp"

TEMP_DIR = Path("/tmp/compare-fanta-image-files")  # noqa: S108
DEFAULT_DIFF_DIR = TEMP_DIR / "diffs"
DOWNSCALED_DIR = TEMP_DIR / "downscaled"

# Guards on emptying the diff dir, whose path comes straight from --diff-dir.
UNSAFE_DIFF_DIRS = frozenset(
    {Path("/"), Path("/tmp"), Path("/var/tmp"), Path.home()}  # noqa: S108
)
MIN_DIFF_DIR_PARTS = 2

app = typer.Typer()
log_level = ""


def _get_lists_to_compare(comic: ComicBook, downscaled_dir: Path) -> tuple[list[Path], list[Path]]:
    restored_files = comic.get_final_srce_story_files(RESTORABLE_PAGE_TYPES)
    original_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    upscayled_files = comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)

    restored_files_to_compare = []
    original_files_to_compare = []
    for (final_file, final_mod), (orig_file, _orig_mod), (upscayl_file, upscayl_mod) in zip(
        restored_files, original_files, upscayled_files, strict=True
    ):
        if final_mod != ModifiedType.ORIGINAL:
            continue

        restored_files_to_compare.append(final_file)

        if upscayl_mod != ModifiedType.ORIGINAL:
            # Any non-ORIGINAL mod means the upscayled file came from the upscayled fixes
            # tree, and that hand-edited file - not the original scan - is what the restore
            # worked from. MODIFIED and ADDED both land here: ADDED means there is no
            # original scan at all, so comparing against one asks for a file that is not
            # there. Only the fixes file has the page, at upscayled size, so downscale it.
            srce_image = load_pil_image_for_reading(final_file).convert("RGB")
            downscaled_file = (
                downscaled_dir / f"down-scaled-{comic.get_fanta_volume()}-{final_file.name}"
            )
            downscale_png(
                srce_image.width,
                srce_image.height,
                upscayl_file,
                downscaled_file,
                compress_level=0,
                quality=0,
            )
            original_files_to_compare.append(downscaled_file)
        else:
            original_files_to_compare.append(orig_file)

    assert len(restored_files_to_compare) == len(original_files_to_compare)

    return restored_files_to_compare, original_files_to_compare


def _format_volume_list(volumes: set[int]) -> str:
    """Render volume numbers as a compact list, collapsing consecutive runs.

    A whole-library run names 30 volumes, which as a bare list buries the one
    thing the summary is for - the scope of what was compared.

    Args:
        volumes: The volume numbers to render.

    Returns:
        A string like "1-4, 7, 9-11". Empty if there are no volumes.

    """
    runs: list[list[int]] = []
    for vol in sorted(volumes):
        if runs and vol == runs[-1][1] + 1:
            runs[-1][1] = vol
        else:
            runs.append([vol, vol])

    return ", ".join(str(lo) if lo == hi else f"{lo}-{hi}" for lo, hi in runs)


def _log_compared_scope(num_files: int, volumes: set[int]) -> None:
    """Log what the run actually got through, ahead of its pass/fail verdict.

    Args:
        num_files: The number of file pairs compared.
        volumes: The volumes those files came from.

    """
    file_str = "file" if num_files == 1 else "files"
    volume_str = "volume" if len(volumes) == 1 else "volumes"

    logger.info(
        f"Compared {num_files} {file_str} from"
        f" {len(volumes)} {volume_str} ({_format_volume_list(volumes)})."
    )


def _delete_any_downscaled_files(image_dir: Path) -> None:
    # rmtree rather than unlink per item, so that a directory left behind by an
    # interrupted run does not stop the cleanup.
    shutil.rmtree(image_dir, ignore_errors=True)


def print_error_summary(errors: list[tuple[str, CompareError]]) -> None:
    """Print a rich summary table of all comparison errors.

    Args:
        errors: A list of (title, error) pairs collected over all compared titles.

    """
    table = Table(title="Comparison Errors", show_lines=True)
    table.add_column("Title", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta", no_wrap=True)
    table.add_column("File", style="yellow")
    table.add_column("Detail", style="white")

    for title, err in errors:
        table.add_row(title, err.error_type, err.file, err.detail)

    Console().print(table)


def _delete_diff_dir_if_empty(diff_dir: Path) -> None:
    """Delete the title's diff directory if no diffs were written to it.

    Args:
        diff_dir: The per-title diff directory created before the comparison.

    """
    if diff_dir.is_dir() and not any(diff_dir.iterdir()):
        diff_dir.rmdir()


def _clear_diff_dir(diff_dir: Path) -> None:
    """Empty the diff dir so that it ends up holding only this run's diffs.

    Clearing per title is not enough: a previous run over different volumes
    named different titles, and those subdirectories survive to be read as
    current findings.

    The path comes straight from `--diff-dir`, and the bash-era recipes used to
    pass "/tmp", so anything that does not look like a diff dir is left alone.
    The per-title clearing in the run still applies then; it just cannot reach
    titles this run does not visit.

    Args:
        diff_dir: The directory the run will write its per-title diffs into.

    Raises:
        ValueError: If the path exists and is not a directory. Saying so is better than
            leaving it for the mkdir that follows, which fails with a bare FileExistsError
            that says nothing about which argument was wrong.

    """
    resolved = diff_dir.resolve()

    if resolved.exists() and not resolved.is_dir():
        msg = f'Diff dir is not a directory: "{resolved}".'
        raise ValueError(msg)

    # A shared or top-level directory is never ours to empty.
    if resolved in UNSAFE_DIFF_DIRS or len(resolved.parts) <= MIN_DIFF_DIR_PARTS:
        logger.warning(
            f'Not clearing diff dir "{resolved}": it is a shared or top-level directory.'
            f" Diffs from previous runs over other titles may still be there."
        )
        return

    # This tool only ever puts per-title directories at the top level, so loose
    # files mean the dir is being used for something else as well.
    if resolved.is_dir() and any(child.is_file() for child in resolved.iterdir()):
        logger.warning(
            f'Not clearing diff dir "{resolved}": it holds loose files, so it is probably'
            f" not only a diff dir. Diffs from previous runs may still be there."
        )
        return

    shutil.rmtree(resolved, ignore_errors=True)


@app.command(
    help="Compares the images in Fantagraphics original and restored directories by title or volume"
)
def main(  # noqa: PLR0913
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    diff_dir: Path = DEFAULT_DIFF_DIR,
    fuzz: Annotated[
        str,
        typer.Option(
            "--fuzz",
            help="Fuzz factor for comparison (e.g., '5%')\n"
            "A value of '0%' uses the RMSE metric instead of AE.",
        ),
    ] = "5%",
    ae_cutoff: Annotated[
        float,
        typer.Option(
            "--ae_cutoff",
            help="AE (Absolute Error) pixel count cutoff for non-zero fuzz.\n"
            "Required if fuzz is not '0%' (unless --ae-cutoff-pct is given).",
        ),
    ] = 0.0,
    ae_cutoff_pct: Annotated[
        float | None,
        typer.Option(
            "--ae-cutoff-pct",
            help="AE cutoff as a percentage of each image's total pixels.\n"
            "Overrides --ae_cutoff when set (resolution-independent).",
        ),
    ] = None,
    tile_size: Annotated[
        int | None,
        typer.Option(
            "--tile-size",
            help="Enable regional comparison: split each page into ~this-size (px)\n"
            "tiles and flag a page if any tile differs too much. Replaces the\n"
            "whole-page AE cutoff; use with --tile-cutoff-pct.",
        ),
    ] = None,
    tile_cutoff_pct: Annotated[
        float | None,
        typer.Option(
            "--tile-cutoff-pct",
            help="In tiled mode, flag a page if any tile's differing-pixel\n"
            "percentage exceeds this.",
        ),
    ] = None,
    calibrate: Annotated[
        bool,
        typer.Option(
            "--calibrate",
            help="Print the per-image figure (AE, or worst tile in tiled mode) at\n"
            "--fuzz without applying a cutoff, to help choose a cutoff.",
        ),
    ] = False,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    _clear_diff_dir(diff_dir)
    diff_dir.mkdir(parents=True, exist_ok=True)

    # Scratch space this run alone owns. The downscaled files are a run's private
    # working state, but they used to be written to a fixed path shared by every
    # run, and the run that finished first removed the whole of it. A run still
    # comparing then failed on its own downscaled file as a missing image.
    DOWNSCALED_DIR.mkdir(parents=True, exist_ok=True)
    run_downscaled_dir = Path(tempfile.mkdtemp(prefix="fcmp-", dir=DOWNSCALED_DIR))

    try:
        comics_database, titles = get_comic_titles(volumes_str, title_str)

        errors: list[tuple[str, CompareError]] = []
        calibration_results: list[CalibrationResult] = []
        # Only the volumes a compared file actually came from, so that the count and the
        # volume list in the summary are about the same set of files. A title whose pages
        # were all skipped has already said so, and adds nothing here.
        num_files_compared = 0
        volumes_compared: set[int] = set()
        for title in titles:
            logger.info(f'Comparing images in {title}"...')

            title_downscaled_dir = run_downscaled_dir / title
            title_downscaled_dir.mkdir(parents=True, exist_ok=True)

            # Normally already empty, the whole diff dir having been cleared above.
            # This is what still holds when that had to be refused.
            image_diff_dir = diff_dir / title
            shutil.rmtree(image_diff_dir, ignore_errors=True)
            image_diff_dir.mkdir(parents=True, exist_ok=True)

            comic_book = comics_database.get_comic_book(title)
            restored_files, original_files = _get_lists_to_compare(comic_book, title_downscaled_dir)

            if len(restored_files) == 0:
                logger.warning(f'No restored files need to be compared for "{title}".')
            else:
                num_files_compared += len(restored_files)
                volumes_compared.add(comic_book.get_fanta_volume())

                title_errors = compare_image_lists(
                    restored_files,
                    original_files,
                    fuzz,
                    ae_cutoff,
                    image_diff_dir,
                    ae_cutoff_pct=ae_cutoff_pct,
                    calibrate=calibrate,
                    tile_size=tile_size,
                    tile_cutoff_pct=tile_cutoff_pct,
                    calibration_out=calibration_results,
                    label=f"Vol {comic_book.get_fanta_volume()} / {title}",
                )
                errors += [(title, err) for err in title_errors]

            _delete_any_downscaled_files(title_downscaled_dir)
            _delete_diff_dir_if_empty(image_diff_dir)

        if not titles:
            # Reported as a failure, not a success: asking for a volume that does
            # not exist compares nothing, and "all equivalent" would read as a pass.
            logger.error("Error: No titles matched. Nothing was compared.")
            sys.exit(1)

        _log_compared_scope(num_files_compared, volumes_compared)

        if calibrate:
            log_calibration_summary(calibration_results)
            if len(calibration_results) > 0:
                logger.info("Calibration complete. Use the figures above to choose a cutoff.")
        elif errors:
            logger.error(f"Comparison failed with {len(errors)} errors.")
            print_error_summary(errors)
        else:
            logger.success("Comparison successful. All directories are equivalent.")

        # Exit with a plain pass/fail status: an error *count* would be truncated
        # modulo 256 by the shell, so exactly 256 errors would look like success.
        sys.exit(1 if errors else 0)
    finally:
        # Ours and only ours. Nothing sweeps the shared parent any more, so a run
        # that dies partway has to take its own scratch with it or leave it there
        # for good.
        shutil.rmtree(run_downscaled_dir, ignore_errors=True)


if __name__ == "__main__":
    app()
