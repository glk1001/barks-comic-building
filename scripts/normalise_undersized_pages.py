"""Bring an undersized volume's original scans up to the library's page size.

Most Fantagraphics volumes arrive with body pages already at 2175x3000. A few do not -
volume 30's scans are 1522x2100 - and at 2100px tall they fail the build's
`MIN_HD_SRCE_HEIGHT` gate, so the volume cannot enter the pipeline at all.

The magnification wanted is only about 1.43x, which is not a scale any upscaler offers.
So each page is enlarged 2x by the project's usual backend and then taken back down to
the target with a Lanczos resize. Going up first and down after is what keeps the result
sharper than a straight 1.43x interpolation would be.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import typer
from comic_utils.common_typer_options import LogLevelArg
from comic_utils.pil_image_utils import downscale_to_exact_size
from loguru import logger
from loguru_config import LoguruConfig
from PIL import Image

from barks_comic_building.restore.image_checks import (
    MAX_THUMBNAIL_DEVIATION,
    get_thumbnail_deviation,
)
from barks_comic_building.restore.upscale_image import (
    DEFAULT_UPSCALER,
    UpscalerArg,
    upscale_image_file,
)

APP_LOGGING_NAME = "norm"

Image.MAX_IMAGE_PIXELS = None

app = typer.Typer()
log_level = ""

# The upscale factor asked of the backend before the resize back down. 2 rather than 4:
# the net magnification wanted is 1.43x, and going up to 4x only to throw three quarters
# of it away compounds the backend's artifacts for no gain that survives the downscale.
UPSCALE_FACTOR = 2

# What each source page size is normalised to. A map rather than a formula so that a page
# whose size is not one of the known ones stops the run instead of being silently resized
# to something nobody chose.
#
# The body pages are the whole point: 2175x3000 is what the rest of the library's originals
# are. Exact aspect would put them at 2174.3 wide, so 2175 is a 0.03% horizontal stretch,
# taken deliberately to land on the standard size. The covers are wider than the body pages
# in this volume as in every other, so they keep their own aspect at the same 1.4286x
# factor rather than being squashed to the body size.
TARGET_SIZES: dict[tuple[int, int], tuple[int, int]] = {
    (1522, 2100): (2175, 3000),  # body page
    (1542, 2100): (2203, 3000),  # cover
}

# Volume 30's pages come in under .jpg names, and the names have to stay .jpg because the
# original tree's page paths are built as `page_num + JPG_FILE_EXT`. Each normalised page is
# written in whatever format its own name gives, so those pages come out as real jpg and the
# 4x upscale still to come starts from jpg data.
PAGE_GLOB = "*.jpg"

# The enlarged intermediate is always png whatever the page is: it is thrown away as soon as
# the resize below has read it, so a lossy generation there would cost quality for nothing.
INTERMEDIATE_EXTENSION = ".png"


def _get_target_size(in_file: Path) -> tuple[int, int]:
    """Return the size the given page is to be normalised to.

    Args:
        in_file: The source page.

    Returns:
        The target width and height.

    Raises:
        ValueError: If the page is not one of the known source sizes.

    """
    with Image.open(in_file) as image:
        srce_size = (image.width, image.height)

    target_size = TARGET_SIZES.get(srce_size)
    if target_size is None:
        known = ", ".join(f"{w}x{h}" for w, h in sorted(TARGET_SIZES))
        msg = (
            f"No target size for a {srce_size[0]}x{srce_size[1]} page:"
            f' "{in_file}". Known source sizes are {known}.'
        )
        raise ValueError(msg)

    return target_size


def _normalise_page(in_file: Path, out_file: Path, temp_dir: Path, upscaler: UpscalerArg) -> None:
    """Enlarge one page and resize it down to the library's page size.

    Args:
        in_file: The undersized source page.
        out_file: Where the normalised page is written. Its extension picks the format.
        temp_dir: Scratch space for the enlarged intermediate.
        upscaler: Which backend to enlarge with.

    Raises:
        RuntimeError: If the normalised page does not match its source, which means
            the enlarge or the resize produced a blank or truncated image. The
            unusable output is deleted first.

    """
    target_size = _get_target_size(in_file)

    # upscale_image_file insists on a .png destination, so the intermediate cannot just
    # carry the page's own name. It is also the file that gets the recipe metadata; the
    # normalised page below is a plain resize of it and keeps none of that.
    upscaled_file = temp_dir / (in_file.stem + INTERMEDIATE_EXTENSION)
    try:
        upscale_image_file(in_file, upscaled_file, UPSCALE_FACTOR, upscaler)

        downscale_to_exact_size(target_size[0], target_size[1], upscaled_file, out_file)
    finally:
        upscaled_file.unlink(missing_ok=True)

    # The enlarge checks itself against its source, but the resize after it does not, and
    # the failure this library keeps meeting - a correctly sized page that is all black -
    # looks like success everywhere else. So the finished page is checked against the
    # source it came from, which covers both steps at once.
    deviation = get_thumbnail_deviation(in_file, out_file)
    if deviation > MAX_THUMBNAIL_DEVIATION:
        out_file.unlink(missing_ok=True)
        msg = (
            f"The normalised page does not match its source (mean deviation"
            f" {deviation:.1f} > {MAX_THUMBNAIL_DEVIATION}) - it is probably black"
            f" or truncated. Check that nothing else was using the GPU."
        )
        raise RuntimeError(msg)

    logger.info(
        f'Normalised "{in_file.name}" to {target_size[0]}x{target_size[1]} (deviation'
        f" {deviation:.1f})."
    )


@app.command(help="Upscale a directory of undersized pages to the library's page size")
def main(
    input_dir: Path,
    output_dir: Path,
    upscaler: UpscalerArg = DEFAULT_UPSCALER,
    log_level_str: LogLevelArg = "INFO",
) -> None:
    """Normalise every page in a directory, skipping ones already done.

    Args:
        input_dir: The directory of undersized pages.
        output_dir: Where the normalised pages are written.
        upscaler: Which backend to enlarge with.
        log_level_str: The console log level.

    """
    # Global variable accessed by loguru-config.
    global log_level  # noqa: PLW0603
    log_level = log_level_str
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    if not input_dir.is_dir():
        logger.error(f'Could not find the input directory: "{input_dir}".')
        sys.exit(1)

    in_files = sorted(input_dir.glob(PAGE_GLOB))
    if not in_files:
        logger.error(f'No "{PAGE_GLOB}" pages in "{input_dir}".')
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # A directory this run alone owns: the intermediates are 2x pages, and a run sharing
    # a fixed scratch path with another would have its files removed out from under it.
    temp_dir = Path(tempfile.mkdtemp(prefix="normalise-pages-"))

    num_done = 0
    num_skipped = 0
    failures: list[tuple[str, str]] = []
    try:
        logger.info(f'Normalising {len(in_files)} pages from "{input_dir}".')

        # One page at a time, never in parallel: two jobs over the one GPU bring on the
        # Vulkan device-lost failure, which is recorded against the upscayl tile size in
        # upscale_image but is really about the GPU being asked for two things at once.
        for in_file in in_files:
            out_file = output_dir / in_file.name
            if out_file.is_file():
                logger.debug(f'Already normalised - skipping: "{out_file.name}".')
                num_skipped += 1
                continue

            try:
                _normalise_page(in_file, out_file, temp_dir, upscaler)
                num_done += 1
            except (OSError, RuntimeError, ValueError) as exc:
                # A bad page does not stop the run: the rest are independent of it, and a
                # 250 page run that gives up at page 3 wastes everything it had done.
                logger.error(f'Failed to normalise "{in_file.name}": {exc}')
                failures.append((in_file.name, str(exc)))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    logger.info(
        f"Normalised {num_done}, skipped {num_skipped} already done, failed {len(failures)}."
    )
    if failures:
        for name, error in failures:
            logger.error(f'Failed: "{name}": {error}')
        sys.exit(1)

    logger.success(f'All pages normalised into "{output_dir}".')


if __name__ == "__main__":
    app()
