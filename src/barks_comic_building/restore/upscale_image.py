import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from barks_fantagraphics.comics_utils import get_clean_path
from comic_utils.pil_image_utils import add_png_metadata
from loguru import logger
from PIL import Image, ImageChops, ImageStat

Image.MAX_IMAGE_PIXELS = None


class Upscaler(StrEnum):
    """The upscaling backends that can be used to enlarge a page."""

    UPSCAYL = "upscayl"
    WAIFU2X = "waifu2x"


DEFAULT_UPSCALER = Upscaler.WAIFU2X

UpscalerArg = Annotated[Upscaler, typer.Option("--upscaler", help="Upscaling backend")]

OUTPUT_FORMAT = "png"
OUTPUT_EXTENSION = ".png"

UPSCAYL_BIN = Path.home() / ".local/share/upscayl/bin/upscayl-bin"
UPSCAYL_MODELS_DIR = Path.home() / ".local/share/upscayl/models"
UPSCAYL_MODEL = "ultramix_balanced"
UPSCAYL_SCALES = (2, 3, 4)

# Upscayl's auto tile size ("0") is broken on Ubuntu 26.04: the Vulkan submit fails with
# VK_ERROR_DEVICE_LOST, after which Upscayl writes an all-black image and still exits 0. A
# custom tile size avoids it, the same as the "Custom Tile Size" setting in the Upscayl GUI.
# Tile sizes from 32 to 144 all work, 160 and above fail the same way as auto does. Running
# two Upscayl jobs over the same GPU at once also brings on the failure, whatever the tile
# size, so keep batch runs sequential. waifu2x is unaffected and needs no tile size.
UPSCAYL_TILE_SIZE = 100

WAIFU2X_DIR = Path.home() / ".local/share/waifu2x-ncnn-vulkan"
WAIFU2X_BIN = WAIFU2X_DIR / "waifu2x-ncnn-vulkan"
WAIFU2X_MODEL = "cunet"
WAIFU2X_MODELS_DIR = WAIFU2X_DIR / f"models-{WAIFU2X_MODEL}"
WAIFU2X_SCALES = (1, 2, 4, 8, 16, 32)

# Denoise level 1 measured best on flat restored art: it takes the JPEG ringing down a little
# while leaving the flat fills alone. Levels 2 and 3 denoise harder but start shifting the flat
# colours, which matters more than the ringing on this material.
WAIFU2X_NOISE_LEVEL = 1

# A broken run still exits 0 and writes a correctly sized PNG that is all black, or blacked out
# below the first few rows, so every result is compared against its source. A genuine upscale
# keeps the coarse thumbnails within a couple of levels of each other, while a corrupt one is
# over a hundred levels away - anything in between is unexplained, so reject it.
CHECK_THUMBNAIL_SIZE = (64, 64)
MAX_THUMBNAIL_DEVIATION = 25.0


def _get_upscayl_run_args(in_file: Path, out_file: Path, scale: int) -> list[str]:
    return [
        str(UPSCAYL_BIN),
        "-i",
        str(in_file),
        "-o",
        str(out_file),
        "-s",
        str(scale),
        "-n",
        UPSCAYL_MODEL,
        "-f",
        OUTPUT_FORMAT,
        "-c",
        "0",
        "-t",
        str(UPSCAYL_TILE_SIZE),
        "-m",
        str(UPSCAYL_MODELS_DIR),
        "-v",
    ]


def _get_waifu2x_run_args(in_file: Path, out_file: Path, scale: int) -> list[str]:
    return [
        str(WAIFU2X_BIN),
        "-i",
        str(in_file),
        "-o",
        str(out_file),
        "-s",
        str(scale),
        "-n",
        str(WAIFU2X_NOISE_LEVEL),
        "-f",
        OUTPUT_FORMAT,
        "-m",
        str(WAIFU2X_MODELS_DIR),
        "-v",
    ]


def _get_run_args(upscaler: Upscaler, in_file: Path, out_file: Path, scale: int) -> list[str]:
    if upscaler == Upscaler.UPSCAYL:
        return _get_upscayl_run_args(in_file, out_file, scale)
    return _get_waifu2x_run_args(in_file, out_file, scale)


def _get_metadata(upscaler: Upscaler, in_file: Path, scale: int) -> dict[str, str]:
    metadata = {
        "Srce file": f'"{get_clean_path(in_file)}"',
        "Scale": str(scale),
        "Upscaler": str(upscaler),
    }

    if upscaler == Upscaler.UPSCAYL:
        # Kept under its old key so the metadata of previously upscayled pages still lines up.
        metadata["Upscayl model"] = UPSCAYL_MODEL
    else:
        metadata["Waifu2x model"] = WAIFU2X_MODEL
        metadata["Waifu2x noise level"] = str(WAIFU2X_NOISE_LEVEL)

    return metadata


def _check_upscaler_is_usable(upscaler: Upscaler, scale: int) -> None:
    binary = UPSCAYL_BIN if upscaler == Upscaler.UPSCAYL else WAIFU2X_BIN
    if not binary.is_file():
        msg = f'Could not find the {upscaler} binary: "{binary}".'
        raise FileNotFoundError(msg)

    scales = UPSCAYL_SCALES if upscaler == Upscaler.UPSCAYL else WAIFU2X_SCALES
    if scale not in scales:
        msg = f"{upscaler} cannot scale by {scale} - it only handles {list(scales)}."
        raise ValueError(msg)


def _get_check_thumbnail(image_file: Path) -> Image.Image:
    with Image.open(image_file) as image:
        return image.convert("RGB").resize(CHECK_THUMBNAIL_SIZE, Image.Resampling.BOX)


def _check_upscaled_output(upscaler: Upscaler, in_file: Path, out_file: Path, scale: int) -> None:
    with Image.open(in_file) as in_image:
        expected_width, expected_height = in_image.width * scale, in_image.height * scale
    with Image.open(out_file) as out_image:
        out_width, out_height = out_image.size

    if abs(out_width - expected_width) > 1 or abs(out_height - expected_height) > 1:
        msg = (
            f"{upscaler} wrote a {out_width}x{out_height} image"
            f" but {expected_width}x{expected_height} was expected."
        )
        raise RuntimeError(msg)

    difference = ImageChops.difference(
        _get_check_thumbnail(in_file),
        _get_check_thumbnail(out_file),
    )
    channel_means = ImageStat.Stat(difference).mean
    deviation = sum(channel_means) / len(channel_means)

    if deviation > MAX_THUMBNAIL_DEVIATION:
        msg = (
            f"{upscaler} exited cleanly but its image does not match the source"
            f" (mean deviation {deviation:.1f} > {MAX_THUMBNAIL_DEVIATION}) - it is"
            f" probably black or truncated. Check that nothing else was using the GPU."
        )
        if upscaler == Upscaler.UPSCAYL:
            msg += f" Then try a smaller UPSCAYL_TILE_SIZE than {UPSCAYL_TILE_SIZE}."
        raise RuntimeError(msg)


def upscale_image_file(
    in_file: Path,
    out_file: Path,
    scale: int = 2,
    upscaler: Upscaler = DEFAULT_UPSCALER,
) -> None:
    """Enlarge an image by the given scale, using the given upscaling backend.

    Args:
        in_file: The image to enlarge.
        out_file: Where to write the enlarged png.
        scale: How much bigger the output should be than the input.
        upscaler: Which backend to run.

    Raises:
        FileNotFoundError: If the backend's binary is not installed.
        ValueError: If the backend cannot handle the requested scale.
        RuntimeError: If the backend fails, or returns an image that does not
            match the source. The unusable output file is deleted first.

    """
    assert out_file.suffix == OUTPUT_EXTENSION

    _check_upscaler_is_usable(upscaler, scale)

    run_args = _get_run_args(upscaler, in_file, out_file, scale)
    process = subprocess.Popen(run_args, stdout=subprocess.PIPE, text=True)  # noqa: S603

    while True:
        output = process.stdout.readline()  # ty: ignore[unresolved-attribute]
        if output == "" and process.poll() is not None:
            break
        if output:
            logger.info(output.strip())

    rc = process.poll()
    if rc != 0:
        msg = f"{upscaler} failed."
        raise RuntimeError(msg)

    try:
        _check_upscaled_output(upscaler, in_file, out_file, scale)
    except RuntimeError:
        # Leaving a corrupt file behind would make the batch runs skip it from then on.
        out_file.unlink(missing_ok=True)
        raise

    add_png_metadata(out_file, _get_metadata(upscaler, in_file, scale))
