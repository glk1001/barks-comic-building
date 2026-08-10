"""Tests for the inpaint writing something the rest of the pipeline can read.

Volume 4's pages 098 and 099 were diagnosed for a day as blank output from a broken gmic.
They were never blank. matchpatch blends a little past white - 258 and 259 were measured on
098 - and gmic answers a value over 255 by writing a 16 bit png. Every reader here rescales
one down by dividing by 257, so a page holding 0 to 259 arrives as every pixel zero. The
files on disk were perfectly good pages the whole time.

Two things came out of that, and both are tested here. The inpaint clamps its output to the
8 bit range, so the values that provoke a 16 bit write never occur. And a 16 bit png is now
a fault in its own right, named as itself, so the next one cannot be mistaken for a blank
page - which is how volume 16's page 062 came to be sitting in the library displaying as
solid black with nothing looking for it.
"""

from __future__ import annotations

import struct
import zlib
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from barks_comic_building.restore import inpaint as inpaint_module
from barks_comic_building.restore.image_checks import find_structural_fault
from barks_comic_building.restore.inpaint import inpaint_image_file

if TYPE_CHECKING:
    from pathlib import Path

SIZE = (400, 600)
EIGHT_BIT = 8


def write_png(path: Path, pixels: np.ndarray) -> Path:
    Image.fromarray(pixels).save(str(path))

    return path


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def write_16_bit_png(path: Path, value: int, size: tuple[int, int] = (40, 30)) -> Path:
    """Write a real 16 bit RGB png holding 8-bit-range values, as gmic does on overshoot.

    Assembled by hand because PIL cannot write one: its 16 bit support is grayscale
    (``I;16``), which it then converts by clamping rather than by rescaling, so a PIL-made
    file does not reproduce the defect at all. The real files are colour type 2 at 16 bits,
    and that is what has to be under test.
    """
    width, height = size
    # width, height, then bit depth 16, colour type 2 (RGB), and three zeros for
    # compression, filter and interlace.
    header = struct.pack(">II", width, height) + bytes([16, 2, 0, 0, 0])
    row = struct.pack(">H", value) * (width * 3)
    raw = b"".join(b"\x00" + row for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )

    return path


def get_bit_depth(path: Path) -> int:
    header = path.read_bytes()[:26]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"

    return header[24]


def _make_picture() -> np.ndarray:
    """Make a page with enough variation in it to read as a picture, not a fill."""
    return np.random.default_rng(7).integers(0, 256, (SIZE[1], SIZE[0], 3), dtype=np.uint8)


class FakeGmic:
    """Stand in for gmic, recording the command and writing what the test asks for.

    Writes 16 bit unless the command clamps, which is exactly what the real thing does.
    """

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, params: list[str]) -> None:
        from pathlib import Path  # noqa: PLC0415

        self.commands.append(list(params))
        out_file = Path(params[-1])
        clamped = "cut" in params
        if clamped:
            write_png(out_file, _make_picture())
        else:
            write_16_bit_png(out_file, 259, SIZE)


@pytest.fixture
def gmic(monkeypatch: pytest.MonkeyPatch) -> FakeGmic:
    fake = FakeGmic()
    monkeypatch.setattr(inpaint_module, "run_gmic", fake)

    return fake


@pytest.fixture
def page(tmp_path: Path) -> Path:
    return write_png(tmp_path / "099.png", np.full((SIZE[1], SIZE[0], 3), 180, dtype=np.uint8))


@pytest.fixture
def ink_mask(tmp_path: Path) -> Path:
    pixels = np.full((SIZE[1], SIZE[0], 3), 255, np.uint8)
    pixels[100:200] = 0

    return write_png(tmp_path / "099-removed-colors.png", pixels)


class TestTheInpaintClampsWhatItWrites:
    def test_the_command_clamps_to_the_8_bit_range(
        self, tmp_path: Path, page: Path, ink_mask: Path, gmic: FakeGmic
    ) -> None:
        """Without this gmic writes 16 bit as soon as matchpatch blends past white."""
        inpaint_image_file(tmp_path, "099", page, ink_mask, tmp_path / "out.png")

        assert len(gmic.commands) == 1
        command = gmic.commands[0]
        assert "cut" in command
        assert "0,255" in command

    def test_the_clamp_comes_before_the_output(
        self, tmp_path: Path, page: Path, ink_mask: Path, gmic: FakeGmic
    ) -> None:
        """Clamping after the write would leave the file on disk still 16 bit."""
        inpaint_image_file(tmp_path, "099", page, ink_mask, tmp_path / "out.png")

        command = gmic.commands[0]
        assert command.index("cut") < command.index("output")

    @pytest.mark.usefixtures("gmic")
    def test_the_written_page_is_readable(self, tmp_path: Path, page: Path, ink_mask: Path) -> None:
        out = tmp_path / "out.png"

        inpaint_image_file(tmp_path, "099", page, ink_mask, out)

        assert get_bit_depth(out) == EIGHT_BIT
        assert find_structural_fault(out) is None


class TestA16BitPageIsAFaultInItsOwnRight:
    """So the next one is reported as itself rather than as a blank page."""

    def test_it_is_found(self, tmp_path: Path) -> None:
        deep = write_16_bit_png(tmp_path / "deep.png", 259)

        fault = find_structural_fault(deep)

        assert fault is not None
        assert "16-bit png" in fault

    def test_the_message_says_what_to_do_about_it(self, tmp_path: Path) -> None:
        fault = find_structural_fault(write_16_bit_png(tmp_path / "deep.png", 259))

        assert fault is not None
        assert "clamped" in fault

    def test_it_is_not_reported_as_a_blank_page(self, tmp_path: Path) -> None:
        """The misdiagnosis this exists to prevent: PIL reads it as every pixel zero."""
        deep = write_16_bit_png(tmp_path / "deep.png", 259)

        with Image.open(deep) as image:
            # PIL really does see black, or as near as makes no difference: dividing by 257
            # sends everything under 257 to zero and leaves 258 and 259 as one. On the real
            # page that meant nine non-black pixels out of a hundred million, which is what
            # every blankness test in this project duly reported as a blank page.
            assert np.asarray(image.convert("RGB")).max() <= 1

        fault = find_structural_fault(deep)

        assert fault is not None
        assert "same colour" not in fault

    def test_the_depth_is_read_before_the_pixels(self, tmp_path: Path) -> None:
        """Checked from the header, since PIL cannot be trusted to see what it mishandles."""
        deep = tmp_path / "truncated.png"
        good = write_png(tmp_path / "good.png", np.zeros((4, 4, 3), np.uint8))
        data = bytearray(good.read_bytes())
        data[24] = 16
        deep.write_bytes(bytes(data))

        fault = find_structural_fault(deep)

        assert fault is not None
        assert "16-bit png" in fault

    def test_an_8_bit_page_passes(self, tmp_path: Path) -> None:
        pixels = np.random.default_rng(1).integers(0, 256, (SIZE[1], SIZE[0], 3), dtype=np.uint8)

        assert find_structural_fault(write_png(tmp_path / "ok.png", pixels)) is None

    def test_a_file_that_is_not_a_png_is_left_to_the_other_checks(self, tmp_path: Path) -> None:
        """The depth test must not swallow the "this is not an image at all" case."""
        not_a_png = tmp_path / "notes.png"
        not_a_png.write_text("this was never a png")

        fault = find_structural_fault(not_a_png)

        assert fault is not None
        assert "16-bit" not in fault


def test_a_short_file_does_not_crash_the_depth_test(tmp_path: Path) -> None:
    """A truncated write is a real thing; it must reach the reader's error, not an IndexError."""
    stub = tmp_path / "stub.png"
    stub.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13))

    fault = find_structural_fault(stub)

    assert fault is not None
