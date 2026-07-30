from __future__ import annotations

import os
from typing import TYPE_CHECKING

import cairosvg
import cv2 as cv
import oxipng
from comic_utils.comic_consts import JPG_FILE_EXT, PNG_FILE_EXT
from comic_utils.pil_image_utils import (
    METADATA_PROPERTY_GROUP,
    SAVE_JPG_COMPRESS_LEVEL,
    SAVE_JPG_QUALITY,
    SAVE_PNG_COMPRESSION,
    add_png_metadata,
    load_pil_image_from_bytes,
)
from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo

from barks_comic_building.restore.gmic_exe import run_gmic

if TYPE_CHECKING:
    from pathlib import Path

Image.MAX_IMAGE_PIXELS = None

# The traced line art rasterises to a huge, almost entirely flat rgba image, so the
# cheapest compression setting still shrinks it enormously while barely costing anything.
# Measured on a 4x page (8864x12224): level 0 wrote 433MB in 1.7s, level 1 wrote 8.1MB in
# 2.0s. Storing it raw was costing fifty times the disk for a third of a second.
_FAST_PNG_COMPRESSION = 1

# The zero-length chunk every finished png ends with: length, type, and its fixed crc.
_PNG_IEND_CHUNK = b"\x00\x00\x00\x00IEND\xaeB\x60\x82"


def svg_file_to_png(svg_file: Path, png_file: Path) -> None:
    png_image = cairosvg.svg2png(url=str(svg_file), scale=1, background_color=None)

    # svg2png returns the bytes unless it was handed a 'write_to' target, which it wasn't.
    assert png_image is not None

    pil_image = load_pil_image_from_bytes(png_image, ext=PNG_FILE_EXT)
    pil_image.save(str(png_file), optimize=False, compress_level=_FAST_PNG_COMPRESSION)


def svg_file_to_optimized_png(
    svg_file: Path, output_width: int, output_height: int, png_file: Path
) -> None:
    png_image = cairosvg.svg2png(
        url=str(svg_file),
        scale=1,
        background_color=None,
        output_width=output_width,
        output_height=output_height,
    )

    # No 'write_to' target here either, so the bytes come back.
    assert png_image is not None

    pil_image = load_pil_image_from_bytes(png_image, ext=PNG_FILE_EXT)
    mask = ImageOps.invert(pil_image.getchannel("A"))
    mask.save(str(png_file), optimize=True, compress_level=SAVE_PNG_COMPRESSION)
    oxipng.optimize(str(png_file), level=6)


def read_png_metadata(png_file: Path) -> dict[str, str]:
    """Read back the metadata a png was written with, without its ``BARKS:`` prefix.

    Reads only the chunks that precede the image data. This is worth being deliberate
    about, because deciding what a run has left to do reads the metadata of every page in
    the library: ``Image.text`` also returns text written *after* the image data, but can
    only get there by decoding the image, which is 1.5s on a 4x page against 6ms here.
    Everything in this codebase writes its metadata through ``pnginfo=`` at save time,
    which Pillow puts before the image data.

    A file not ending in an IEND chunk is treated as unreadable. A write killed part way
    leaves the text chunks in place with no pixels behind them, and reporting its metadata
    would let a half written page pass as a finished one - which the full decode used to
    prevent as a side effect, and this checks on purpose.

    Args:
        png_file: The png to read.

    Returns:
        The metadata, keyed without the group prefix. Empty if the file has none, is
        incomplete, or cannot be read as a png.

    """
    prefix = f"{METADATA_PROPERTY_GROUP}:"

    if not _is_complete_png(png_file):
        return {}

    try:
        with Image.open(str(png_file)) as pil_image:
            text = dict(pil_image.info)
    except (OSError, ValueError):
        return {}

    # `info` holds the other png chunks too, whose keys and values are not all strings.
    return {
        key.removeprefix(prefix): value
        for key, value in text.items()
        if isinstance(key, str) and key.startswith(prefix) and isinstance(value, str)
    }


def _is_complete_png(png_file: Path) -> bool:
    """Return whether a png ends with the IEND chunk that closes a finished file.

    Args:
        png_file: The png to check.

    Returns:
        True if the file ends in IEND. False if it does not, or is too short to, or
        cannot be read.

    """
    try:
        with png_file.open("rb") as f:
            f.seek(-len(_PNG_IEND_CHUNK), os.SEEK_END)
            return f.read(len(_PNG_IEND_CHUNK)) == _PNG_IEND_CHUNK
    except OSError:
        return False


def write_cv_image_file(
    file: Path, image: cv.typing.MatLike, metadata: dict[str, str] | None = None
) -> None:
    if file.suffix == JPG_FILE_EXT:
        _write_cv_jpeg_file(file, image, metadata)
        return

    if file.suffix == PNG_FILE_EXT:
        _write_cv_png_file(file, image, metadata)
        return

    cv.imwrite(str(file), image)


def resize_image_file(
    in_file: Path, srce_scale: int, resized_file: Path, metadata: dict[str, str]
) -> None:
    if resized_file.suffix == JPG_FILE_EXT:
        _resize_jpeg_file(in_file, srce_scale, resized_file, metadata)
        return

    if resized_file.suffix == PNG_FILE_EXT:
        _resize_png_file(in_file, srce_scale, resized_file, metadata)
        return

    raise AssertionError


def _resize_jpeg_file(
    in_file: Path, srce_scale: int, resized_file: Path, metadata: dict[str, str]
) -> None:
    image = cv.imread(str(in_file))
    assert image is not None
    scale = 1.0 / srce_scale
    image = cv.resize(image, (0, 0), fx=scale, fy=scale, interpolation=cv.INTER_AREA)
    write_cv_image_file(resized_file, image, metadata)


def _resize_png_file(
    in_file: Path, srce_scale: int, resized_file: Path, metadata: dict[str, str]
) -> None:
    assert srce_scale in [2, 4]
    scale_percent = 25 if srce_scale == 4 else 50  # noqa: PLR2004

    resize_cmd = [
        str(in_file),
        "+resize[-1]",
        f"{scale_percent}%,{scale_percent}%,1,3,2",
        "output[-1]",
        str(resized_file),
    ]

    run_gmic(resize_cmd)

    add_png_metadata(resized_file, metadata)


def _write_cv_png_file(
    file: Path, image: cv.typing.MatLike, metadata: dict[str, str] | None
) -> None:
    color_converted = cv.cvtColor(image, cv.COLOR_BGR2RGB)
    pil_image = Image.fromarray(color_converted)

    png_metadata = PngInfo()
    if metadata:
        for key, value in metadata.items():
            png_metadata.add_text(f"{METADATA_PROPERTY_GROUP}:{key}", value)

    pil_image.save(
        str(file), pnginfo=png_metadata, optimize=True, compress_level=SAVE_PNG_COMPRESSION
    )


def _write_cv_jpeg_file(
    file: Path, image: cv.typing.MatLike, metadata: dict[str, str] | None
) -> None:
    comments_str = "" if metadata is None else "\n" + "\n".join(_get_metadata_as_list(metadata))
    color_converted = cv.cvtColor(image, cv.COLOR_BGR2RGB)
    pil_image = Image.fromarray(color_converted)
    pil_image.save(
        str(file),
        optimize=True,
        compress_level=SAVE_JPG_COMPRESS_LEVEL,
        quality=SAVE_JPG_QUALITY,
        comment=comments_str,
    )


def _get_metadata_as_list(metadata: dict[str, str]) -> list[str]:
    metadata_list = []

    for key, value in metadata.items():
        metadata_list.append(f"{METADATA_PROPERTY_GROUP}:{key}={value}")

    return metadata_list
