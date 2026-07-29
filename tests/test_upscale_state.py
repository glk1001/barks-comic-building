"""Tests for the decision to skip a page or upscayl it again.

The failure that matters is silent: calling a stale page current would leave it out of a
re-run started precisely to redo it. The library was upscayled with Upscayl and carries no
recipe at all, so "no recipe recorded" has to read as stale rather than as done.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from barks_comic_building.restore import upscale_image
from barks_comic_building.restore.upscale_image import (
    Upscaler,
    check_upscaler_is_usable,
    upscale_image_file,
)
from barks_comic_building.restore.upscale_state import (
    RECIPE_ID_KEY,
    UPSCALE_DATE_KEY,
    UpscalePageState,
    get_upscale_page_status,
)

if TYPE_CHECKING:
    from pathlib import Path

CURRENT_RECIPE_ID = "aaaaaaaaaaaa"
OLD_RECIPE_ID = "bbbbbbbbbbbb"
UPSCALE_DATE = "2026-07-29T18:00:00+10:00"


def write_png(path: Path, metadata: dict[str, str] | None = None) -> Path:
    """Write a tiny png, optionally carrying BARKS metadata."""
    info = PngInfo()
    for key, value in (metadata or {}).items():
        info.add_text(f"BARKS:{key}", value)

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2)).save(str(path), pnginfo=info)

    return path


class Page:
    """The two files a page's upscale state is decided from."""

    def __init__(self, tmp_path: Path) -> None:
        self.srce = tmp_path / "srce.jpg"
        self.upscayl = tmp_path / "upscayl.png"

    def state(self) -> UpscalePageState:
        return get_upscale_page_status(self.srce, self.upscayl, CURRENT_RECIPE_ID).state

    def write_all(self, recipe_id: str | None) -> None:
        write_png(self.srce)
        metadata = {RECIPE_ID_KEY: recipe_id, UPSCALE_DATE_KEY: UPSCALE_DATE} if recipe_id else None
        write_png(self.upscayl, metadata)


@pytest.fixture
def page(tmp_path: Path) -> Page:
    return Page(tmp_path)


class TestUpscalePageState:
    def test_no_srce_cannot_be_upscayled(self, page: Page) -> None:
        assert page.state() is UpscalePageState.NO_SRCE

    def test_no_output_is_missing(self, page: Page) -> None:
        write_png(page.srce)

        assert page.state() is UpscalePageState.MISSING

    def test_matching_recipe_is_current(self, page: Page) -> None:
        page.write_all(CURRENT_RECIPE_ID)

        assert page.state() is UpscalePageState.CURRENT

    def test_different_recipe_is_stale(self, page: Page) -> None:
        page.write_all(OLD_RECIPE_ID)

        assert page.state() is UpscalePageState.STALE

    def test_no_recipe_at_all_is_stale(self, page: Page) -> None:
        """Every page upscayled before provenance was kept, which is the whole library."""
        page.write_all(recipe_id=None)

        assert page.state() is UpscalePageState.STALE

    def test_unreadable_output_is_stale_not_current(self, page: Page) -> None:
        """A truncated write must never be mistaken for a finished page."""
        page.write_all(CURRENT_RECIPE_ID)
        page.upscayl.write_bytes(b"not a png")

        assert page.state() is UpscalePageState.STALE

    def test_a_symlinked_output_belongs_to_another_volume(self, page: Page, tmp_path: Path) -> None:
        """Collection titles borrow pages from other volumes by symlink.

        Queueing one would upscale it through the link, replacing that volume's page with
        an upscale of a different source image.
        """
        other_volume_page = write_png(tmp_path / "other" / "123.png")
        write_png(page.srce)
        page.upscayl.symlink_to(other_volume_page)

        assert page.state() is UpscalePageState.LINKED

    def test_a_symlink_is_linked_even_when_it_is_broken(self, page: Page, tmp_path: Path) -> None:
        """Writing would create the missing file at the far end, in the other volume."""
        write_png(page.srce)
        page.upscayl.symlink_to(tmp_path / "other" / "gone.png")

        assert page.state() is UpscalePageState.LINKED

    def test_the_date_is_read_back(self, page: Page) -> None:
        page.write_all(CURRENT_RECIPE_ID)

        status = get_upscale_page_status(page.srce, page.upscayl, CURRENT_RECIPE_ID)

        assert status.upscale_date == UPSCALE_DATE
        assert status.recipe_id == CURRENT_RECIPE_ID


class TestNeedsUpscayling:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (UpscalePageState.CURRENT, False),
            (UpscalePageState.NO_SRCE, False),
            (UpscalePageState.LINKED, False),
            (UpscalePageState.STALE, True),
            (UpscalePageState.MISSING, True),
        ],
    )
    def test_only_the_fixable_states_are_queued(
        self, state: UpscalePageState, *, expected: bool
    ) -> None:
        """Only the states an upscale can actually fix are queued.

        NO_SRCE must not be, because there is nothing to upscayl from - a run that queued
        it would fail the page on every attempt forever.
        """
        assert state.needs_upscayling is expected


class TestTheWriterRefusesToo:
    """The page state keeps linked pages out of a run; this keeps them safe anyway.

    A guard in only one of the two places would leave `single_upscayl` and
    `directory_upscayl` able to do the damage.
    """

    def test_upscaling_onto_a_symlink_is_refused(self, tmp_path: Path) -> None:
        other_volume_page = write_png(tmp_path / "other" / "123.png")
        before = other_volume_page.read_bytes()

        out_file = tmp_path / "500.png"
        out_file.symlink_to(other_volume_page)

        with pytest.raises(ValueError, match="symlink"):
            upscale_image_file(write_png(tmp_path / "srce.png"), out_file, 4)

        assert other_volume_page.read_bytes() == before


class TestRunLevelPreconditions:
    """Things true for every page or none belong before the loop, not inside it."""

    def test_a_missing_binary_is_checked_once_up_front(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(upscale_image, "WAIFU2X_BIN", tmp_path / "not-installed")
        with pytest.raises(FileNotFoundError, match="binary"):
            check_upscaler_is_usable(Upscaler.WAIFU2X, 4)

    def test_an_impossible_scale_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot scale"):
            check_upscaler_is_usable(Upscaler.UPSCAYL, 7)
