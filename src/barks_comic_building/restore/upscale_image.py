import subprocess
from pathlib import Path

from barks_fantagraphics.comics_utils import get_clean_path
from comic_utils.pil_image_utils import add_png_metadata
from loguru import logger
from PIL import Image, ImageChops, ImageStat

Image.MAX_IMAGE_PIXELS = None

UPSCAYL_BIN = Path.home() / ".local/share/upscayl/bin/upscayl-bin"
UPSCAYL_MODELS_DIR = Path.home() / ".local/share/upscayl/models"
UPSCAYL_MODEL = "ultramix_balanced"
UPSCAYL_OUTPUT_FORMAT = "png"
UPSCAYL_OUTPUT_EXTENSION = ".png"

# Upscayl's auto tile size ("0") is broken on Ubuntu 26.04: the Vulkan submit fails with
# VK_ERROR_DEVICE_LOST, after which Upscayl writes an all-black image and still exits 0. A
# custom tile size avoids it, the same as the "Custom Tile Size" setting in the Upscayl GUI.
# Tile sizes from 32 to 144 all work, 160 and above fail the same way as auto does. Running
# two Upscayl jobs over the same GPU at once also brings on the failure, whatever the tile
# size, so keep batch runs sequential.
UPSCAYL_TILE_SIZE = 100

# A broken Upscayl run still exits 0 and writes a correctly sized PNG that is all black, or
# blacked out below the first few rows, so every result is compared against its source. A
# genuine upscale keeps the coarse thumbnails within a couple of levels of each other, while a
# corrupt one is over a hundred levels away - anything in between is unexplained, so reject it.
UPSCAYL_CHECK_THUMBNAIL_SIZE = (64, 64)
UPSCAYL_MAX_THUMBNAIL_DEVIATION = 25.0


def _get_check_thumbnail(image_file: Path) -> Image.Image:
    with Image.open(image_file) as image:
        return image.convert("RGB").resize(UPSCAYL_CHECK_THUMBNAIL_SIZE, Image.Resampling.BOX)


def _check_upscayl_output(in_file: Path, out_file: Path, scale: int) -> None:
    with Image.open(in_file) as in_image:
        expected_width, expected_height = in_image.width * scale, in_image.height * scale
    with Image.open(out_file) as out_image:
        out_width, out_height = out_image.size

    if abs(out_width - expected_width) > 1 or abs(out_height - expected_height) > 1:
        msg = (
            f"Upscayl wrote a {out_width}x{out_height} image"
            f" but {expected_width}x{expected_height} was expected."
        )
        raise RuntimeError(msg)

    difference = ImageChops.difference(
        _get_check_thumbnail(in_file),
        _get_check_thumbnail(out_file),
    )
    channel_means = ImageStat.Stat(difference).mean
    deviation = sum(channel_means) / len(channel_means)

    if deviation > UPSCAYL_MAX_THUMBNAIL_DEVIATION:
        msg = (
            f"Upscayl exited cleanly but its image does not match the source"
            f" (mean deviation {deviation:.1f} >"
            f" {UPSCAYL_MAX_THUMBNAIL_DEVIATION}) - it is probably black or"
            f" truncated. Check that nothing else was using the GPU, then try a"
            f" smaller UPSCAYL_TILE_SIZE than {UPSCAYL_TILE_SIZE}."
        )
        raise RuntimeError(msg)


def upscale_image_file(in_file: Path, out_file: Path, scale: int = 2) -> None:
    assert out_file.suffix == UPSCAYL_OUTPUT_EXTENSION

    run_args = [
        UPSCAYL_BIN,
        "-i",
        str(in_file),
        "-o",
        str(out_file),
        "-s",
        str(scale),
        "-n",
        UPSCAYL_MODEL,
        "-f",
        UPSCAYL_OUTPUT_FORMAT,
        "-c",
        "0",
        "-t",
        str(UPSCAYL_TILE_SIZE),
        "-m",
        str(UPSCAYL_MODELS_DIR),
        "-v",
    ]

    process = subprocess.Popen(run_args, stdout=subprocess.PIPE, text=True)  # noqa: S603

    while True:
        output = process.stdout.readline()  # ty: ignore[unresolved-attribute]
        if output == "" and process.poll() is not None:
            break
        if output:
            logger.info(output.strip())

    rc = process.poll()
    if rc != 0:
        msg = "Upscayl failed."
        raise RuntimeError(msg)

    try:
        _check_upscayl_output(in_file, out_file, scale)
    except RuntimeError:
        # Leaving a corrupt file behind would make the batch runs skip it from then on.
        out_file.unlink(missing_ok=True)
        raise

    metadata = {
        "Srce file": f'"{get_clean_path(in_file)}"',
        "Scale": str(scale),
        "Upscayl model": UPSCAYL_MODEL,
    }
    add_png_metadata(out_file, metadata)
