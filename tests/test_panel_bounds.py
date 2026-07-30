"""Tests for when a page's panel bounds are recomputed and when they are left alone.

Panel bounds are expensive - Kumiko runs per page - so an existing file is normally
skipped, which is what makes a re-run over a whole volume cheap. `--force` exists for the
case that skip cannot serve: the bounds are already there but wrong, because the page was
re-restored or a hand-drawn override was added underneath them.

The failure worth guarding is the quiet one in each direction. A `--force` that did not
actually reach the per-page decision would silently do nothing and leave the bad bounds in
place; a default run that stopped skipping would recompute the whole library. So both are
asserted against a processor that records whether it was asked to do any work.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import pytest

from barks_comic_building.restore.batch_panel_bounds import get_page_panel_bounds

if TYPE_CHECKING:
    from pathlib import Path

    from comic_utils.panel_bounding_box_processor import BoundingBoxProcessor

SEGMENT_INFO: dict[str, Any] = {"panels": [[0, 0, 100, 200]]}


class FakeBoundingBoxProcessor:
    """A Kumiko wrapper that records whether it was asked to do anything.

    Stands in for a `BoundingBoxProcessor`: only the two methods the per-page function
    calls are implemented, so the skip-or-recompute decision can be checked without
    running Kumiko.
    """

    def __init__(self) -> None:
        self.kumiko_calls: list[Path] = []
        self.saved: list[Path] = []

    def get_panels_segment_info_from_kumiko(
        self, srce_file: Path, _override_dir: Path
    ) -> dict[str, Any]:
        self.kumiko_calls.append(srce_file)

        return SEGMENT_INFO

    def save_panels_segment_info(self, dest_file: Path, segment_info: dict[str, Any]) -> None:
        self.saved.append(dest_file)
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_text(json.dumps(segment_info))


def as_processor(fake: FakeBoundingBoxProcessor) -> BoundingBoxProcessor:
    """Present the fake as the processor the per-page function is typed against."""
    return cast("BoundingBoxProcessor", fake)


class Page:
    """One page's source scan and its panel bounds file."""

    def __init__(self, tmp_path: Path) -> None:
        self.override_dir = tmp_path / "fixes" / "bounded"
        self.srce_file = tmp_path / "restored" / "042.png"
        self.dest_file = tmp_path / "segments" / "042.json"
        self.srce_file.parent.mkdir(parents=True, exist_ok=True)
        self.srce_file.touch()

    def already_bounded(self, text: str = "stale bounds") -> None:
        """Put an existing panel bounds file in place, as an earlier run would leave it."""
        self.dest_file.parent.mkdir(parents=True, exist_ok=True)
        self.dest_file.write_text(text)


@pytest.fixture
def page(tmp_path: Path) -> Page:
    return Page(tmp_path)


def run(page: Page, processor: FakeBoundingBoxProcessor, *, force: bool) -> None:
    """Run the per-page bounds step for one page."""
    get_page_panel_bounds(
        as_processor(processor),
        page.override_dir,
        page.srce_file,
        page.dest_file,
        force=force,
    )


class TestAPageWithNoBoundsYet:
    def test_the_bounds_are_computed(self, page: Page) -> None:
        processor = FakeBoundingBoxProcessor()

        run(page, processor, force=False)

        assert processor.kumiko_calls == [page.srce_file]
        assert processor.saved == [page.dest_file]

    def test_force_makes_no_difference(self, page: Page) -> None:
        processor = FakeBoundingBoxProcessor()

        run(page, processor, force=True)

        assert processor.kumiko_calls == [page.srce_file]


class TestAPageThatAlreadyHasBounds:
    def test_it_is_skipped_by_default(self, page: Page) -> None:
        # What keeps a re-run over a whole volume cheap.
        page.already_bounded()
        processor = FakeBoundingBoxProcessor()

        run(page, processor, force=False)

        assert processor.kumiko_calls == []
        assert processor.saved == []

    def test_the_existing_file_is_left_untouched_when_skipped(self, page: Page) -> None:
        page.already_bounded("do not overwrite me")

        run(page, FakeBoundingBoxProcessor(), force=False)

        assert page.dest_file.read_text() == "do not overwrite me"

    def test_force_recomputes_it(self, page: Page) -> None:
        # The case skipping cannot serve: the bounds exist but are wrong, because the page
        # was re-restored or an override was added under it.
        page.already_bounded()
        processor = FakeBoundingBoxProcessor()

        run(page, processor, force=True)

        assert processor.kumiko_calls == [page.srce_file]
        assert processor.saved == [page.dest_file]

    def test_force_overwrites_the_existing_file(self, page: Page) -> None:
        page.already_bounded("stale bounds")

        run(page, FakeBoundingBoxProcessor(), force=True)

        assert json.loads(page.dest_file.read_text()) == SEGMENT_INFO


class TestAPageStagedFromAnotherVolume:
    """A one-pager staged into a synthetic collection, whose dest file is a symlink.

    The page's real files live in its home volume; the collection only borrows them. So
    the bounds are that volume's to make, and computing them here writes through the link.
    Worse than a duplicated effort: the override directory used would be the collection's,
    keyed by the collection page number (508) rather than the home volume's (176), so a
    hand-drawn override that exists is not found and the page is silently rewritten
    without it. That is not hypothetical - it happened to five pages.
    """

    def test_it_is_skipped_even_under_force(self, page: Page) -> None:
        home_file = page.dest_file.with_name("176.json")
        home_file.parent.mkdir(parents=True, exist_ok=True)
        home_file.write_text("the home volume's bounds, made with its own override")
        page.dest_file.symlink_to(home_file)
        processor = FakeBoundingBoxProcessor()

        run(page, processor, force=True)

        assert processor.kumiko_calls == []
        assert processor.saved == []

    def test_the_home_volumes_file_is_not_written_through(self, page: Page) -> None:
        home_file = page.dest_file.with_name("176.json")
        home_file.parent.mkdir(parents=True, exist_ok=True)
        home_file.write_text("do not write through me")
        page.dest_file.symlink_to(home_file)

        run(page, FakeBoundingBoxProcessor(), force=True)

        assert home_file.read_text() == "do not write through me"

    def test_a_dangling_link_is_not_written_through_either(self, page: Page) -> None:
        # Restaged since, or the home volume's file removed. Either way it is not this
        # run's page to make, and creating it here would populate another volume's tree.
        page.dest_file.parent.mkdir(parents=True, exist_ok=True)
        page.dest_file.symlink_to(page.dest_file.with_name("gone.json"))
        processor = FakeBoundingBoxProcessor()

        run(page, processor, force=True)

        assert processor.kumiko_calls == []


class TestAPageWithNoSourceScan:
    def test_nothing_is_computed(self, page: Page) -> None:
        page.srce_file.unlink()
        processor = FakeBoundingBoxProcessor()

        run(page, processor, force=True)

        assert processor.kumiko_calls == []

    def test_it_does_not_raise(self, page: Page) -> None:
        # Every page runs on a process pool, so one unreadable page is logged and the rest
        # of the volume carries on rather than the batch dying.
        page.srce_file.unlink()

        run(page, FakeBoundingBoxProcessor(), force=True)
