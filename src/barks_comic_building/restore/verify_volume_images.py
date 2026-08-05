import time
from pathlib import Path

import typer
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg, VolumesArg
from intspan import intspan
from loguru import logger
from PIL import Image

from barks_comic_building.cli_setup import init_logging
from barks_comic_building.restore.image_checks import find_structural_fault

APP_LOGGING_NAME = "vimg"
Image.MAX_IMAGE_PIXELS = None  # disables the DOS warning


def verify_image_files(
    comics_database: ComicsDatabase, volumes: list[int], do_restored: bool
) -> None:
    start = time.time()

    num_images_checked = 0
    num_errors = 0
    for volume in volumes:
        logger.info(f'Verifying all images files in all dirs for Fanta volume "{volume}"...')

        n, e = verify_volume_dirs(comics_database, volume, do_restored)
        num_images_checked += n
        num_errors += e

    if num_errors == 0:
        logger.info("\nThere were no errors.")
    else:
        logger.error(f"\nThere were {num_errors} errors.")

    logger.info(
        f"\nTime taken to verify all {num_images_checked} files: {int(time.time() - start)}s."
    )


def verify_volume_dirs(
    comic_database: ComicsDatabase, volume: int, do_restored: bool
) -> tuple[int, int]:
    num_images_checked = 0
    num_errors = 0

    def _accumulate(d: Path) -> None:
        nonlocal num_images_checked, num_errors
        n, e = verify_volume_dir(d)
        num_images_checked += n
        num_errors += e

    _accumulate(comic_database.get_fantagraphics_volume_image_dir(volume))
    _accumulate(comic_database.get_fantagraphics_fixes_volume_image_dir(volume))
    _accumulate(comic_database.get_fantagraphics_upscayled_volume_image_dir(volume))
    _accumulate(comic_database.get_fantagraphics_upscayled_fixes_volume_image_dir(volume))

    if do_restored:
        _accumulate(comic_database.get_fantagraphics_restored_volume_image_dir(volume))
        _accumulate(comic_database.get_fantagraphics_restored_upscayled_volume_image_dir(volume))
        _accumulate(comic_database.get_fantagraphics_restored_svg_volume_image_dir(volume))

    return num_images_checked, num_errors


def verify_volume_dir(volume_dir: Path) -> tuple[int, int]:
    logger.info(f'Verifying volume dir: "{volume_dir}".')

    num_image_files = 0
    num_errors = 0

    for image_file in volume_dir.iterdir():
        if image_file.is_dir():
            logger.debug(f'Skipping directory: "{image_file}".')
            continue
        if image_file.suffix == ".txt":
            logger.debug(f'Skipping txt file: "{image_file}".')
            continue
        if image_file.suffix == ".svg":
            logger.debug(f'Skipping svg file: "{image_file}".')
            continue

        fault = find_file_fault(image_file)
        if fault is not None:
            logger.error(f'File "{image_file}": {fault}.')
            num_errors += 1

        num_image_files += 1

    return num_image_files, num_errors


def find_file_fault(image_file: Path) -> str | None:
    """Return what is wrong with an image file on disk, or None if it is sound.

    Every pixel is decoded rather than just the header, because the damage worth finding
    here hides behind a well-formed one - a correct signature, a proper trailing IEND, and
    a pixel stream zlib will not touch. Reading a whole volume is minutes rather than
    seconds because of it, which is why this is a command you run and not a step in a
    build.

    The source comparison is deliberately not run - pairing every tree with what it was
    made from is a different job, and it is the writing stages that have the source to
    hand. What is left still finds both kinds of damage this sweep was built for.

    Args:
        image_file: The file to check.

    Returns:
        A description of the fault, or None.

    Raises:
        FileNotFoundError: If the path is not a file.

    """
    if not image_file.is_file():
        msg = f'"{image_file}" is not a file.'
        raise FileNotFoundError(msg)

    return find_structural_fault(image_file)


app = typer.Typer()


@app.command(help="Verify volume images files")
def main(
    volumes_str: VolumesArg = "",
    do_restored: bool = False,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    init_logging(APP_LOGGING_NAME, "verify-volume-image-files.log", log_level_str)

    volumes = list(intspan(volumes_str))
    comics_database = ComicsDatabase()

    verify_image_files(comics_database, volumes, do_restored)


if __name__ == "__main__":
    app()
