"""Tests for the checks that refuse a bad page rather than writing it.

Both real failures are built here rather than described, because they are unalike enough
that a check aimed at one sails past the other. A png with a flipped byte in its pixel
stream still has a correct header and a proper trailing IEND, so nothing short of decoding
it notices. A blacked-out page decodes perfectly and is the right size, so only comparing
it against what it was made from notices.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from barks_comic_building.restore.image_checks import (
    MAX_THUMBNAIL_DEVIATION,
    find_content_fault,
    find_structural_fault,
    get_thumbnail_deviation,
)

if TYPE_CHECKING:
    from pathlib import Path

SIZE = (64, 48)


def write_picture(path: Path, *, shade: int = 0) -> Path:
    """Write a png with enough variation in it to be a picture rather than a fill."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", SIZE)
    image.putdata(
        [
            ((x * 4 + shade) % 256, (y * 5 + shade) % 256, (x + y) % 256)
            for y in range(SIZE[1])
            for x in range(SIZE[0])
        ]
    )
    image.save(str(path))

    return path


def write_flat(path: Path, colour: tuple[int, int, int] = (0, 0, 0)) -> Path:
    """Write a png of one colour - the shape of a page with none of the content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", SIZE, colour).save(str(path))

    return path


def corrupt_pixel_data(path: Path) -> Path:
    """Flip a byte inside the compressed pixel stream, leaving the file well-formed.

    The result is what volume 1's page 144 looked like when it was read badly: correct
    signature, every chunk in place, a proper trailing IEND, and a pixel stream that zlib
    will not decompress.
    """
    data = bytearray(path.read_bytes())

    offset = 8
    while offset < len(data) - 8:
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        if data[offset + 4 : offset + 8] == b"IDAT":
            # Past the zlib header, so the damage is in the deflate stream itself.
            data[offset + 10] ^= 0xFF
            path.write_bytes(bytes(data))
            return path
        offset += 12 + length

    msg = f'No IDAT chunk to corrupt in "{path}".'
    raise AssertionError(msg)


class TestAWellFormedPngCanStillBeUnreadable:
    """The case the IEND test in `image_io` waves through."""

    def test_a_damaged_pixel_stream_is_found(self, tmp_path: Path) -> None:
        broken = corrupt_pixel_data(write_picture(tmp_path / "broken.png"))

        fault = find_structural_fault(broken)

        assert fault is not None
        assert "pixel data could not be read" in fault

    def test_the_damaged_file_still_looks_finished(self, tmp_path: Path) -> None:
        """Which is why opening it is not enough - the header alone reads fine."""
        broken = corrupt_pixel_data(write_picture(tmp_path / "broken.png"))

        assert broken.read_bytes().endswith(b"IEND\xaeB`\x82")
        with Image.open(broken) as image:
            assert image.size == SIZE

    def test_a_file_that_is_not_an_image_is_found(self, tmp_path: Path) -> None:
        not_an_image = tmp_path / "notes.png"
        not_an_image.write_text("this was never a png")

        assert find_structural_fault(not_an_image) is not None

    def test_a_file_that_was_never_written_is_found(self, tmp_path: Path) -> None:
        assert find_structural_fault(tmp_path / "absent.png") == "the file was not written"

    def test_a_sound_page_passes(self, tmp_path: Path) -> None:
        assert find_structural_fault(write_picture(tmp_path / "good.png")) is None


class TestTheShapeOfTheOutput:
    def test_the_wrong_size_is_found(self, tmp_path: Path) -> None:
        fault = find_structural_fault(write_picture(tmp_path / "p.png"), expected_size=(10, 10))

        assert fault is not None
        assert "64x48 but 10x10" in fault

    def test_the_right_size_passes(self, tmp_path: Path) -> None:
        assert find_structural_fault(write_picture(tmp_path / "p.png"), expected_size=SIZE) is None

    def test_being_one_pixel_out_is_allowed(self, tmp_path: Path) -> None:
        """A resize rounds, so a page can legitimately land a pixel wide of the division.

        Volume 8's page 162 is 8702 across and comes back 2176 rather than 2175. Testing
        the size exactly would fail it on every run.
        """
        one_out = (SIZE[0] + 1, SIZE[1] - 1)

        assert (
            find_structural_fault(write_picture(tmp_path / "p.png"), expected_size=one_out) is None
        )

    def test_being_two_pixels_out_is_not(self, tmp_path: Path) -> None:
        two_out = (SIZE[0] + 2, SIZE[1])

        assert find_structural_fault(write_picture(tmp_path / "p.png"), expected_size=two_out)

    def test_the_wrong_mode_is_found(self, tmp_path: Path) -> None:
        fault = find_structural_fault(write_picture(tmp_path / "p.png"), expected_mode="L")

        assert fault is not None
        assert 'mode "RGB"' in fault

    def test_the_mode_is_not_checked_unless_asked(self, tmp_path: Path) -> None:
        """The traced ink is written as a palette png, so a blanket RGB check is wrong."""
        palette = tmp_path / "ink.png"
        write_picture(palette)
        with Image.open(palette) as image:
            image.convert("P").save(str(palette))

        assert find_structural_fault(palette) is None


class TestABlankedPageIsTheRightShapeAndTheWrongPicture:
    """Volume 3's 251, 254, 257 and 259 - flawless pngs of nothing."""

    def test_a_flat_page_is_found_without_needing_its_source(self, tmp_path: Path) -> None:
        fault = find_structural_fault(write_flat(tmp_path / "black.png"))

        assert fault is not None
        assert "every pixel is the same colour" in fault

    def test_a_flat_white_page_is_found_too(self, tmp_path: Path) -> None:
        """Not just black: a page of any one colour has none of the content."""
        white = write_flat(tmp_path / "white.png", (255, 255, 255))

        assert find_structural_fault(white) is not None

    def test_a_blacked_out_page_is_nowhere_near_its_source(self, tmp_path: Path) -> None:
        srce = write_picture(tmp_path / "srce.png")
        blacked = write_flat(tmp_path / "out.png")

        assert get_thumbnail_deviation(srce, blacked) > MAX_THUMBNAIL_DEVIATION

    def test_a_page_of_the_wrong_picture_is_found(self, tmp_path: Path) -> None:
        """The one a structural check cannot see: valid, right shape, not this page."""
        srce = write_picture(tmp_path / "srce.png", shade=0)
        wrong = write_picture(tmp_path / "out.png", shade=128)

        fault = find_content_fault(wrong, srce, MAX_THUMBNAIL_DEVIATION)

        assert fault is not None
        assert "does not resemble" in fault

    def test_a_page_that_matches_its_source_passes(self, tmp_path: Path) -> None:
        srce = write_picture(tmp_path / "srce.png", shade=0)
        close = write_picture(tmp_path / "out.png", shade=2)

        assert find_content_fault(close, srce, MAX_THUMBNAIL_DEVIATION) is None

    def test_an_identical_page_deviates_by_nothing(self, tmp_path: Path) -> None:
        srce = write_picture(tmp_path / "srce.png")

        assert get_thumbnail_deviation(srce, srce) == pytest.approx(0.0)
