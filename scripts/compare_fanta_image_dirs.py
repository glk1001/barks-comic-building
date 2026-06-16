import sys
from pathlib import Path
from typing import Annotated

import typer
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_helpers import get_comic_titles
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from compare_images import CompareError, compare_image_lists
from loguru import logger
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "fcmp"

app = typer.Typer()
log_level = ""


@app.command(
    help="Compares the images in Fantagraphics original and restored directories by title or volume"
)
def main(  # noqa: PLR0913
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    diff_dir: Path = Path("/tmp"),  # noqa: S108
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

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    errors: list[CompareError] = []
    for title in titles:
        logger.info(f'Comparing images in {title}"...')

        comic_book = comics_database.get_comic_book(title)

        original_files = [
            f[0] for f in comic_book.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
        ]
        restored_files = [
            f[0] for f in comic_book.get_final_srce_story_files(RESTORABLE_PAGE_TYPES)
        ]

        image_diff_dir = diff_dir / title

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
        )

    if calibrate:
        logger.info("Calibration complete. Use the figures above to choose a cutoff.")
    elif errors:
        logger.error(f"Comparison failed with {len(errors)} errors.")
    else:
        logger.success("Comparison successful. All directories are equivalent.")

    sys.exit(len(errors))


if __name__ == "__main__":
    app()
