"""Tests for the decision to skip a page or restore it again.

Two failures matter here and both are silent. Calling a stale page current would leave it
out of a re-run that was started precisely to redo it. Calling a page with missing outputs
current would keep it invisible - which is what the old existence check did, and why over
a hundred pages in the library have a restored png and no 4x file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from barks_comic_building.restore.page_state import (
    RECIPE_ID_KEY,
    PageState,
    get_page_status,
)

if TYPE_CHECKING:
    from pathlib import Path

CURRENT_RECIPE_ID = "aaaaaaaaaaaa"
OLD_RECIPE_ID = "bbbbbbbbbbbb"


def write_png(path: Path, metadata: dict[str, str] | None = None) -> Path:
    """Write a tiny png, optionally carrying BARKS metadata."""
    info = PngInfo()
    for key, value in (metadata or {}).items():
        info.add_text(f"BARKS:{key}", value)

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2)).save(str(path), pnginfo=info)

    return path


class Page:
    """The four files a page's state is decided from."""

    def __init__(self, tmp_path: Path) -> None:
        self.upscayl = tmp_path / "upscayl.png"
        self.restored = tmp_path / "restored.png"
        self.restored_4x = tmp_path / "restored-4x.png"
        self.svg = tmp_path / "restored.svg"

    def status(self) -> PageState:
        return get_page_status(
            self.upscayl, self.restored, self.restored_4x, self.svg, CURRENT_RECIPE_ID
        ).state

    def write_all(self, recipe_id: str | None) -> None:
        write_png(self.upscayl)
        write_png(self.restored, {RECIPE_ID_KEY: recipe_id} if recipe_id else None)
        write_png(self.restored_4x)
        self.svg.write_text("<svg/>")


@pytest.fixture
def page(tmp_path: Path) -> Page:
    return Page(tmp_path)


class TestPageState:
    def test_no_upscayl_input_cannot_be_restored(self, page: Page) -> None:
        assert page.status() is PageState.NO_SRCE

    def test_no_outputs_is_missing(self, page: Page) -> None:
        write_png(page.upscayl)

        assert page.status() is PageState.MISSING

    def test_matching_recipe_is_current(self, page: Page) -> None:
        page.write_all(CURRENT_RECIPE_ID)

        assert page.status() is PageState.CURRENT

    def test_different_recipe_is_stale(self, page: Page) -> None:
        page.write_all(OLD_RECIPE_ID)

        assert page.status() is PageState.STALE

    def test_no_recipe_at_all_is_stale(self, page: Page) -> None:
        """Every page restored before provenance was kept.

        This is what makes the first run after the change redo the library without
        anything having to be deleted by hand.
        """
        page.write_all(recipe_id=None)

        assert page.status() is PageState.STALE

    @pytest.mark.parametrize("missing", ["restored", "restored_4x", "svg"])
    def test_any_missing_output_is_incomplete(self, page: Page, missing: str) -> None:
        """Including when the restored png itself is present and current.

        The old check looked only at the restored png, so a page whose 4x or svg output
        never got written was skipped from then on.
        """
        page.write_all(CURRENT_RECIPE_ID)
        getattr(page, missing).unlink()

        assert page.status() is PageState.INCOMPLETE

    def test_unreadable_restored_png_is_stale_not_current(self, page: Page) -> None:
        """A truncated write must never be mistaken for a finished page."""
        page.write_all(CURRENT_RECIPE_ID)
        page.restored.write_bytes(b"not a png")

        assert page.status() is PageState.STALE


class TestNeedsRestoring:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (PageState.CURRENT, False),
            (PageState.NO_SRCE, False),
            (PageState.STALE, True),
            (PageState.INCOMPLETE, True),
            (PageState.MISSING, True),
        ],
    )
    def test_only_the_fixable_states_are_queued(self, state: PageState, *, expected: bool) -> None:
        """Only the states a restore can actually fix are queued.

        NO_SRCE must not be, because there is nothing to restore from - a run that queued
        it would fail the page on every attempt forever.
        """
        assert state.needs_restoring is expected
