"""The checks that stand between a bad write and a page nobody notices is broken.

Two unrelated things go wrong with a written png, and neither check finds the other's case.

*Structural*: the file is a well-formed png whose pixel stream is damaged. Volume 1's
restored page 144 was one - correct signature, every chunk in place, a proper trailing
IEND, and one IDAT chunk whose CRC32 did not match, so zlib refused the whole stream at
byte 0 of 19,578,000. Nothing short of decoding it finds that, which is why the IEND test
in `image_io` waved it through: the shell of the file was perfect. It sat in the library
unnoticed until someone went looking, and has since been repaired by hand.

*Semantic*: the file decodes perfectly and the picture is wrong. Volume 3's restored pages
251, 254, 257 and 259 are that - valid pngs, right dimensions, every pixel black, written
from sources with the full range of tones. The only way to know is to look at what the page
was made from.

So the structural checks stand alone, and the content check needs the source. Both return a
description of the first fault rather than raising, because the sweep tool wants to report
every page it finds and the pipeline wants to stop on the first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image, ImageChops, ImageStat

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CHECK_THUMBNAIL_SIZE",
    "MAX_THUMBNAIL_DEVIATION",
    "MIN_THUMBNAIL_STDDEV",
    "SIZE_TOLERANCE",
    "find_content_fault",
    "find_structural_fault",
    "get_check_thumbnail",
    "get_thumbnail_deviation",
    "get_thumbnail_stddev",
]

Image.MAX_IMAGE_PIXELS = None

# Small enough that comparing two 8700x12000 pages costs nothing, big enough that a page
# and a blacked-out copy of it are nowhere near each other.
CHECK_THUMBNAIL_SIZE = (64, 64)

# How far a written page may sit from what it was made from. Both stages share it, which
# was not the plan - the restore removes colours, inpaints and overlays ink, so it looked
# like it would need a much looser number than the upscale. Measured instead of guessed,
# and it does not: at this thumbnail size the restore hardly moves the picture at all.
#
# Measured over 400 pages sampled across all 29 volumes, each restored-upscayled page
# against the upscayled page it was made from: 0.5 to 7.2, median 3.0. The four blacked-out
# Silent Night pages that prompted the check: 166.2, 168.5, 172.9, 176.2. Nothing measured
# anywhere between 8 and 166.
#
# So 25 is three and a half times the widest legitimate page and a sixth of the mildest
# corrupt one. Anything in that gap is unexplained, which is reason enough to refuse it.
MAX_THUMBNAIL_DEVIATION = 25.0


# How much a page's thumbnail has to vary before it counts as a picture rather than a
# blank. Nothing real comes close to this: measured across the pages sampled here, a
# restored page's thumbnail spreads 45 to 60, while a blank one is flat at 0.0.
MIN_THUMBNAIL_STDDEV = 2.0


# A png's magic number, and where its IHDR puts the bit depth. Read from the bytes rather
# than asked of PIL, because PIL is one of the readers that gets 16 bit wrong and cannot be
# used to detect the thing it mishandles.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_PNG_IHDR_BIT_DEPTH_OFFSET = 24
_PNG_HEADER_BYTES = 33
_EIGHT_BIT = 8


def _find_bit_depth_fault(image_file: Path) -> str | None:
    """Return a fault if a png was written deeper than 8 bits per channel.

    Nothing downstream of the restore reads a 16 bit png correctly. PIL and OpenCV both
    rescale one down by dividing by 257, so a page whose values sit in 0 to 259 - which is
    what gmic writes when a step blends its way just past white - arrives as every pixel
    zero. Judged a fault rather than worked around: every page in this library is 8 bit, the
    reader expects 8 bit, and a page that is not is broken however it came about.

    Detected here so that it is reported as itself. Volume 4's pages 098 and 099 spent a day
    being diagnosed as blank output from a broken gmic, and the sweep that followed turned up
    volume 16's page 062 sitting in the library in the same state - a page that would have
    displayed as solid black and that nothing was looking for.

    Args:
        image_file: The png to inspect.

    Returns:
        A description of the fault, or None if the file is 8 bit or is not a png.

    """
    with image_file.open("rb") as opened:
        header = opened.read(_PNG_HEADER_BYTES)

    if len(header) < _PNG_HEADER_BYTES or header[: len(_PNG_MAGIC)] != _PNG_MAGIC:
        return None

    bit_depth = header[_PNG_IHDR_BIT_DEPTH_OFFSET]
    if bit_depth <= _EIGHT_BIT:
        return None

    return (
        f"it is a {bit_depth}-bit png, which every reader here misreads as black"
        f" - the step that wrote it needs its output clamped to 0,255"
    )


def _reduce_to_check_thumbnail(image: Image.Image) -> Image.Image:
    return image.convert("RGB").resize(CHECK_THUMBNAIL_SIZE, Image.Resampling.BOX)


def get_check_thumbnail(image_file: Path) -> Image.Image:
    """Return a small RGB thumbnail of an image, for comparing it against another.

    Args:
        image_file: The image to reduce.

    Returns:
        The thumbnail, always RGB and `CHECK_THUMBNAIL_SIZE`.

    """
    with Image.open(image_file) as image:
        return _reduce_to_check_thumbnail(image)


def get_thumbnail_stddev(thumbnail: Image.Image) -> float:
    """Return how much a check thumbnail varies, averaged over its channels.

    Args:
        thumbnail: A thumbnail from `get_check_thumbnail`.

    Returns:
        The mean per-channel standard deviation, 0 for a page of one flat colour.

    """
    channel_stddevs = ImageStat.Stat(thumbnail).stddev

    return sum(channel_stddevs) / len(channel_stddevs)


def get_thumbnail_deviation(image_file: Path, other_file: Path) -> float:
    """Return how far apart two images are, averaged over the channels of a thumbnail.

    Args:
        image_file: One image.
        other_file: The other.

    Returns:
        The mean absolute difference, 0 for identical pictures and up to 255.

    """
    difference = ImageChops.difference(
        get_check_thumbnail(image_file),
        get_check_thumbnail(other_file),
    )
    channel_means = ImageStat.Stat(difference).mean

    return sum(channel_means) / len(channel_means)


# A page whose width is not a multiple of the scale rounds rather than truncates on the way
# back down - volume 8's page 162 is 8702 wide and resizes to 2176, not 2175 - so an exact
# size test would fail a page that is perfectly good. One pixel is all the slack that needs,
# and no real failure is off by one: a truncated or wrongly scaled output is out by hundreds.
SIZE_TOLERANCE = 1


def find_structural_fault(  # noqa: PLR0911
    image_file: Path,
    *,
    expected_size: tuple[int, int] | None = None,
    expected_mode: str | None = None,
) -> str | None:
    """Return what is wrong with a written image, from the file alone.

    Every pixel is decoded, which is the only way to reach a damaged IDAT chunk - a broken
    png can carry a perfectly good header, and `Image.open` alone reads no further.

    Args:
        image_file: The image to check.
        expected_size: The (width, height) it should have, to within `SIZE_TOLERANCE`, or
            None not to check.
        expected_mode: The PIL mode it should have, or None not to check.

    Returns:
        A description of the first fault found, or None if the image is sound.

    """
    if not image_file.is_file():
        return "the file was not written"

    too_deep = _find_bit_depth_fault(image_file)
    if too_deep is not None:
        return too_deep

    try:
        with Image.open(image_file) as image:
            image.load()
            size, mode = image.size, image.mode
            # Asked of a thumbnail rather than of an exact colour count, because the blanks
            # that turn up are not quite uniform and an exact test reads them as pictures:
            # gmic handed back volume 4's page 099 as 104,399,984 black pixels and sixteen
            # stray ones, which `getcolors(maxcolors=1)` waves straight through.
            thumbnail = _reduce_to_check_thumbnail(image)
    except (OSError, SyntaxError, ValueError) as exc:
        # OSError covers PIL's "broken data stream" and "image file is truncated"; the
        # other two cover a file that is not an image at all.
        return f"the pixel data could not be read ({type(exc).__name__}: {exc})"

    if expected_size is not None and any(
        abs(got - want) > SIZE_TOLERANCE for got, want in zip(size, expected_size, strict=True)
    ):
        return f"it is {size[0]}x{size[1]} but {expected_size[0]}x{expected_size[1]} was expected"

    if expected_mode is not None and mode != expected_mode:
        return f'it is mode "{mode}" but "{expected_mode}" was expected'

    spread = get_thumbnail_stddev(thumbnail)
    if spread < MIN_THUMBNAIL_STDDEV:
        # A blanked page: the shape of a picture with none of the content. Blank pages are
        # not a restorable page type, so nothing legitimate lands here.
        colour = tuple(round(mean) for mean in ImageStat.Stat(thumbnail).mean)
        return (
            f"every pixel is effectively the same colour {colour}"
            f" (thumbnail spread {spread:.1f} < {MIN_THUMBNAIL_STDDEV})"
        )

    return None


def find_content_fault(
    image_file: Path,
    srce_file: Path,
    max_deviation: float,
) -> str | None:
    """Return whether a written image is too far from what it was made from.

    Catches the failure a structural check cannot see: a flawless png of the wrong picture.

    Args:
        image_file: The image that was written.
        srce_file: The image it was made from.
        max_deviation: How far apart the two thumbnails may be.

    Returns:
        A description of the fault, or None if the image is close enough to its source.

    """
    deviation = get_thumbnail_deviation(srce_file, image_file)
    if deviation > max_deviation:
        return (
            f"it does not resemble the page it was made from"
            f" (mean deviation {deviation:.1f} > {max_deviation})"
        )

    return None
