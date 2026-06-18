import sys
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

APP_LOGGING_NAME = "fcmp"

TEMP_DIR = Path("/tmp/compare-fanta-image-files")  # noqa: S108
DEFAULT_DIFF_DIR = TEMP_DIR / "diffs"
DOWNSCALED_DIR = TEMP_DIR / "downscaled"

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

        if upscayl_mod == ModifiedType.MODIFIED:
            # We need to downscale the modded upscayled file.
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


def _delete_any_downscaled_files(image_dir: Path) -> None:
    for item in image_dir.iterdir():
        item.unlink()
    image_dir.rmdir()


def _delete_diff_dir_if_empty(diff_dir: Path) -> None:
    """Delete the title's diff directory if no diffs were written to it.

    Args:
        diff_dir: The per-title diff directory created before the comparison.

    """
    if diff_dir.is_dir() and not any(diff_dir.iterdir()):
        diff_dir.rmdir()


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
    diff_dir.mkdir(parents=True, exist_ok=True)

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    errors: list[CompareError] = []
    calibration_results: list[CalibrationResult] = []
    for title in titles:
        logger.info(f'Comparing images in {title}"...')

        title_downscaled_dir = DOWNSCALED_DIR / title
        title_downscaled_dir.mkdir(parents=True, exist_ok=True)
        image_diff_dir = diff_dir / title
        image_diff_dir.mkdir(parents=True, exist_ok=True)

        comic_book = comics_database.get_comic_book(title)
        restored_files, original_files = _get_lists_to_compare(comic_book, title_downscaled_dir)

        if len(restored_files) == 0:
            logger.warning(f'No restored files need to be compared for "{title}".')
        else:
            errors += compare_image_lists(
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
            )

        _delete_any_downscaled_files(title_downscaled_dir)
        _delete_diff_dir_if_empty(image_diff_dir)

    DOWNSCALED_DIR.rmdir()

    if calibrate:
        log_calibration_summary(calibration_results)
        if len(calibration_results) > 0:
            logger.info("Calibration complete. Use the figures above to choose a cutoff.")
    elif errors:
        logger.error(f"Comparison failed with {len(errors)} errors.")
    else:
        logger.success("Comparison successful. All directories are equivalent.")

    sys.exit(len(errors))


if __name__ == "__main__":
    app()
