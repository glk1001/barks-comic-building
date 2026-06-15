import sys
from pathlib import Path
from typing import Annotated

import typer
from comic_utils.common_typer_options import LogLevelArg, VolumesArg
from compare_images import CompareError, compare_images_in_dir
from intspan import intspan
from loguru import logger
from loguru_config import LoguruConfig

APP_LOGGING_NAME = "fcmp"

app = typer.Typer()
log_level = ""


@app.command(help="Compares the images in two Fantagraphics directories")
def main(  # noqa: PLR0913
    dir1: Path,
    dir2: Path,
    volumes_str: VolumesArg,
    diff_dir: Path,
    fuzz: Annotated[
        str,
        typer.Option(
            "--fuzz",
            help="Fuzz factor for comparison (e.g., '5%')\n"
            "A value of '0%' uses the RMSE metric instead of AE.",
        ),
    ],
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
    calibrate: Annotated[
        bool,
        typer.Option(
            "--calibrate",
            help="Print the AE pixel count per image (at --fuzz) without applying a\n"
            "cutoff, to help choose a good --ae_cutoff / --ae-cutoff-pct.",
        ),
    ] = False,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    volumes = list(intspan(volumes_str))

    if not dir1.is_dir():
        msg = f'Error: Could not find Fantagraphics directory1: "{dir1}".'
        raise FileNotFoundError(msg)
    if not dir2.is_dir():
        msg = f'Error: Could not find Fantagraphics directory2: "{dir2}".'
        raise FileNotFoundError(msg)

    errors: list[CompareError] = []
    for file1 in dir1.iterdir():
        if not file1.is_dir():
            msg = f'Error: Expecting dir not file: "{file1}".'
            raise FileExistsError(msg)

        if not any(str(v) in str(file1.name) for v in volumes):
            continue

        logger.info(f'Comparing image dirs in {file1.name}"...')

        image_dir1 = file1 / "images"
        image_dir2 = dir2 / file1.name / "images"
        image_diff_dir = diff_dir / file1.name

        errors += compare_images_in_dir(
            image_dir1,
            image_dir2,
            fuzz,
            ae_cutoff,
            image_diff_dir,
            ae_cutoff_pct=ae_cutoff_pct,
            calibrate=calibrate,
        )

    if calibrate:
        logger.info("Calibration complete. Use the AE counts above to choose a cutoff.")
    elif errors:
        logger.error(f"Comparison failed with {len(errors)} errors.")
    else:
        logger.success("Comparison successful. All directories are equivalent.")

    sys.exit(len(errors))


if __name__ == "__main__":
    app()
