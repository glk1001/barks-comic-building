# ruff: noqa: ERA001

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

import cairosvg
import cv2 as cv
from comic_utils.comic_consts import JPG_FILE_EXT, PNG_FILE_EXT
from comic_utils.pil_image_utils import (
    METADATA_PROPERTY_GROUP,
    SAVE_JPG_COMPRESS_LEVEL,
    SAVE_JPG_QUALITY,
    SAVE_PNG_COMPRESSION,
    add_png_metadata,
)
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from .gmic_exe import run_gmic

if TYPE_CHECKING:
    from pathlib import Path

Image.MAX_IMAGE_PIXELS = None


def svg_file_to_png(svg_file: Path, png_file: Path) -> None:
    # background_color = "white"
    background_color = None
    png_image = cairosvg.svg2png(url=str(svg_file), scale=1, background_color=background_color)

    pil_image = Image.open(BytesIO(png_image))
    pil_image.save(str(png_file), optimize=True, compress_level=SAVE_PNG_COMPRESSION)


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
    scale = 1.0 / srce_scale
    image = cv.resize(image, (0, 0), fx=scale, fy=scale, interpolation=cv.INTER_AREA)
    write_cv_image_file(resized_file, image, metadata)


def _resize_png_file(
    in_file: Path, srce_scale: int, resized_file: Path, metadata: dict[str, str]
) -> None:
    assert srce_scale in [2, 4]
    scale_percent = 25 if srce_scale == 4 else 50

    resize_cmd = [
        str(in_file),
        "+resize[-1]",
        f"{scale_percent}%,{scale_percent}%,1,3,2",
        "output[-1]",
        str(resized_file),
    ]

    run_gmic(resize_cmd)

    add_png_metadata(resized_file, metadata)


def _write_cv_png_file(file: Path, image: cv.typing.MatLike, metadata: dict[str, str]) -> None:
    color_converted = cv.cvtColor(image, cv.COLOR_BGR2RGB)
    pil_image = Image.fromarray(color_converted)

    png_metadata = PngInfo()
    if metadata:
        for key, value in metadata.items():
            png_metadata.add_text(f"{METADATA_PROPERTY_GROUP}:{key}", value)

    pil_image.save(
        str(file), pnginfo=png_metadata, optimize=True, compress_level=SAVE_PNG_COMPRESSION
    )


def _write_cv_jpeg_file(file: Path, image: cv.typing.MatLike, metadata: dict[str, str]) -> None:
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
