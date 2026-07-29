"""Tests for reading a page's provenance back off its png.

Every decision about what a run has left to do is made from this, over every page in the
library, so it has to be both fast and exact. Two properties are pinned here because
neither is obvious from the code and both have a silent failure behind them.

Reading must not decode the image. Pillow's ``text`` attribute also returns text written
after the image data, but reaches it by decoding, which costs 1.5s on a 4x page against
6ms for the chunks before it. Nothing here writes metadata after the image data, so the
cheap read is the correct one - but only as long as that stays true.

An incomplete file must read as having no metadata. The text chunks come before the pixels
and survive a write that was killed, so a half written page would otherwise report a
recipe and be taken for finished.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from comic_utils.pil_image_utils import METADATA_PROPERTY_GROUP, add_png_metadata
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from barks_comic_building.restore.image_io import read_png_metadata

if TYPE_CHECKING:
    from pathlib import Path

RECIPE_ID = "aaaaaaaaaaaa"
RECIPE_JSON = '{"model":"cunet","scale":4}'


@pytest.fixture
def png(tmp_path: Path) -> Path:
    """Return a png carrying metadata, written the way the pipeline writes it."""
    path = tmp_path / "page.png"
    Image.new("RGB", (64, 64)).save(str(path))
    add_png_metadata(path, {"Upscale recipe id": RECIPE_ID, "Upscale recipe": RECIPE_JSON})

    return path


class TestRoundTrip:
    def test_metadata_comes_back_without_its_prefix(self, png: Path) -> None:
        assert read_png_metadata(png) == {
            "Upscale recipe id": RECIPE_ID,
            "Upscale recipe": RECIPE_JSON,
        }

    def test_a_png_with_no_metadata_reads_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "bare.png"
        Image.new("RGB", (8, 8)).save(str(path))

        assert read_png_metadata(path) == {}

    def test_other_keys_are_left_out(self, tmp_path: Path) -> None:
        """Only this project's group is ours to report."""
        path = tmp_path / "mixed.png"
        info = PngInfo()
        info.add_text(f"{METADATA_PROPERTY_GROUP}:Mine", "keep")
        info.add_text("Software", "some other tool")
        Image.new("RGB", (8, 8)).save(str(path), pnginfo=info)

        assert read_png_metadata(path) == {"Mine": "keep"}

    def test_a_file_that_is_not_a_png_reads_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "not.png"
        path.write_bytes(b"not a png")

        assert read_png_metadata(path) == {}

    def test_a_missing_file_reads_as_empty(self, tmp_path: Path) -> None:
        assert read_png_metadata(tmp_path / "gone.png") == {}


class TestIncompleteFiles:
    """A page whose write was killed must not pass as finished."""

    def test_a_truncated_png_reports_no_metadata(self, png: Path) -> None:
        """A half written page must not report a recipe.

        The text chunks precede the pixels, so they survive the kill and would otherwise
        be reported as though the page were whole.
        """
        whole = png.read_bytes()
        png.write_bytes(whole[: len(whole) // 2])

        assert read_png_metadata(png) == {}

    def test_an_empty_file_reports_no_metadata(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.png"
        path.touch()

        assert read_png_metadata(path) == {}

    def test_a_file_shorter_than_the_end_chunk_reports_no_metadata(self, tmp_path: Path) -> None:
        """Seeking back past the start of the file must not raise."""
        path = tmp_path / "tiny.png"
        path.write_bytes(b"\x89PNG")

        assert read_png_metadata(path) == {}


class TestReadsWithoutDecoding:
    def test_it_agrees_with_the_decoding_read(self, png: Path) -> None:
        """The cheap read is only correct while nothing writes metadata after the pixels.

        If a writer ever starts doing that, this fails and says so, rather than pages
        quietly losing the provenance that decides whether they get redone.
        """
        with Image.open(str(png)) as image:
            decoded = {
                key.removeprefix(f"{METADATA_PROPERTY_GROUP}:"): value
                for key, value in dict(getattr(image, "text", {})).items()
                if key.startswith(f"{METADATA_PROPERTY_GROUP}:")
            }

        assert read_png_metadata(png) == decoded

    def test_the_pixels_are_never_loaded(self, png: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decoding must not creep back in.

        Decoding every page of the library costs hours, so make it impossible to
        reintroduce without this failing.
        """

        def fail(*_args: object, **_kwargs: object) -> None:
            msg = "read_png_metadata decoded the image"
            raise AssertionError(msg)

        monkeypatch.setattr(Image.Image, "load", fail)

        assert read_png_metadata(png)["Upscale recipe id"] == RECIPE_ID
