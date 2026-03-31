import time
from pathlib import Path

import typer
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg, VolumesArg
from intspan import intspan
from loguru import logger
from loguru_config import LoguruConfig
from PIL import Image

import barks_comic_building.log_setup as _log_setup

APP_LOGGING_NAME = "vimg"

_RESOURCES = Path(__file__).parent.parent / "resources"
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

        if not verify_file(image_file):
            logger.error(f'File "{image_file}" is not a valid image file.')
            num_errors += 1

        num_image_files += 1

    return num_image_files, num_errors


def verify_file(image_file: Path) -> bool:
    if not image_file.is_file():
        msg = f'"{image_file}" is not a file.'
        raise FileNotFoundError(msg)

    try:
        with Image.open(image_file) as img:
            img.verify()
            return True
    except (OSError, SyntaxError):
        return False


app = typer.Typer()


@app.command(help="Verify volume images files")
def main(
    volumes_str: VolumesArg = "",
    do_restored: bool = False,
    log_level_str: LogLevelArg = "DEBUG",
) -> None:
    _log_setup.log_level = log_level_str
    _log_setup.log_filename = "verify-volume-image-files.log"
    _log_setup.APP_LOGGING_NAME = APP_LOGGING_NAME
    LoguruConfig.load(_RESOURCES / "log-config.yaml")

    volumes = list(intspan(volumes_str))
    comics_database = ComicsDatabase()

    verify_image_files(comics_database, volumes, do_restored)


if __name__ == "__main__":
    app()
