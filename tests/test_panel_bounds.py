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
import typer
from loguru import logger

from barks_comic_building.restore.batch_panel_bounds import (
    PageBoundsOutcome,
    _get_page_pairs,
    _log_run_summary,
    get_page_panel_bounds,
    parse_fanta_pages,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from comic_utils.panel_bounding_box_processor import BoundingBoxProcessor

# A valid segments payload: one panel filling a 100x200 page.
SEGMENT_INFO: dict[str, Any] = {
    "filename": "042_orig.jpg",
    "size": [100, 200],
    "numbering": "ltr",
    "gutters": [0, 0],
    "license": None,
    "panels": [[0, 0, 100, 200]],
    "overall_bounds": [0, 0, 99, 199],
}


class FakeBoundingBoxProcessor:
    """A Kumiko wrapper that records whether it was asked to do anything.

    Stands in for a `BoundingBoxProcessor`: only the two methods the per-page function
    calls are implemented, so the skip-or-recompute decision can be checked without
    running Kumiko.
    """

    def __init__(self, segment_info: dict[str, Any] = SEGMENT_INFO) -> None:
        self.kumiko_calls: list[Path] = []
        self.saved: list[Path] = []
        self._segment_info = segment_info

    def get_panels_segment_info_from_kumiko(
        self, srce_file: Path, _override_dir: Path
    ) -> dict[str, Any]:
        self.kumiko_calls.append(srce_file)

        return self._segment_info

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

    def staged_from_home_volume(self) -> Path:
        """Replace the source scan with the symlink a staged collection page actually has.

        `barks-stage-one-pagers` links the home volume's restored png into the collection,
        falling back to its fixes jpg when that volume is not restored yet. Either way the
        collection's source scan is a link from the moment the page is staged.
        """
        home_file = self.srce_file.with_name("176.png")
        home_file.write_text("the home volume's page")
        self.srce_file.unlink()
        self.srce_file.symlink_to(home_file)

        return home_file


@pytest.fixture
def page(tmp_path: Path) -> Page:
    return Page(tmp_path)


def run(page: Page, processor: FakeBoundingBoxProcessor, *, force: bool) -> PageBoundsOutcome:
    """Run the per-page bounds step for one page."""
    return get_page_panel_bounds(
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
        home_file = page.dest_file.with_name("gone.json")
        page.dest_file.symlink_to(home_file)
        processor = FakeBoundingBoxProcessor()

        run(page, processor, force=True)

        assert processor.kumiko_calls == []
        assert not home_file.exists()


class TestAPageStagedFromAnotherVolumeWithNoBoundsMadeYet:
    """The same one-pager, in the window before its home volume has any bounds at all.

    Staging only links an artifact that already exists, so there is no segments link to
    catch here - the dest file is simply absent, which reads exactly like an ordinary
    unbounded page. It is also the window someone is most likely to be in, because the
    missing bounds are what sent them to this command.

    The write would land in the collection's own tree rather than through a link, which
    makes it quieter than the case above rather than safer: same dropped override, and it
    survives until the next staging run replaces it, so every collection build in between
    bakes in bounds made without the override. The source scan is the signal that is
    already a link this early.
    """

    def test_it_is_skipped(self, page: Page) -> None:
        page.staged_from_home_volume()
        processor = FakeBoundingBoxProcessor()

        run(page, processor, force=False)

        assert processor.kumiko_calls == []
        assert processor.saved == []

    def test_force_does_not_override_the_skip(self, page: Page) -> None:
        page.staged_from_home_volume()
        processor = FakeBoundingBoxProcessor()

        run(page, processor, force=True)

        assert processor.kumiko_calls == []

    def test_no_bounds_file_is_left_behind_in_the_collection(self, page: Page) -> None:
        # The one the link check cannot make: nothing is written through, but a real file
        # in the collection's own segments dir would be just as wrong, and would outlive
        # the run.
        page.staged_from_home_volume()

        run(page, FakeBoundingBoxProcessor(), force=True)

        assert not page.dest_file.exists()


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


@pytest.fixture
def error_log() -> Iterator[list[str]]:
    """Collect loguru ERROR messages emitted while a test runs."""
    messages: list[str] = []
    handler_id = logger.add(lambda msg: messages.append(str(msg)), level="ERROR")
    yield messages
    logger.remove(handler_id)


# Vol 10 p020's panels in kumiko's column-wise order; the reading order is 1,3,2,4.
UNSORTED_SEGMENT_INFO: dict[str, Any] = {
    **SEGMENT_INFO,
    "size": [2216, 3056],
    "panels": [[222, 194, 965, 511], [222, 731, 994, 780], [1189, 194, 885, 648]],
    "overall_bounds": [222, 194, 2073, 1510],
}


class TestInvalidBoundsAreStillWritten:
    """A faulty result is saved and shouted about, not dropped.

    The integrity checker is the gate. Dropping the file would turn one loud fault into a
    quiet "missing dest file" later, and would stall a whole-volume run on one page.
    """

    def test_unsorted_panels_are_saved_and_logged(self, page: Page, error_log: list[str]) -> None:
        processor = FakeBoundingBoxProcessor(UNSORTED_SEGMENT_INFO)

        run(page, processor, force=False)

        assert processor.saved == [page.dest_file]
        assert json.loads(page.dest_file.read_text()) == UNSORTED_SEGMENT_INFO
        assert any("not in reading order" in msg for msg in error_log)
        assert any("anyway" in msg for msg in error_log)

    def test_a_panel_order_override_makes_that_order_valid(
        self, page: Page, error_log: list[str]
    ) -> None:
        page.override_dir.mkdir(parents=True)
        (page.override_dir / "042-panel-order.json").write_text("[1, 3, 2]")

        run(page, FakeBoundingBoxProcessor(UNSORTED_SEGMENT_INFO), force=False)

        assert error_log == []

    def test_overall_bounds_override_allows_a_mismatch(
        self, page: Page, error_log: list[str]
    ) -> None:
        info = {**SEGMENT_INFO, "overall_bounds": [0, 0, 50, 50]}
        run(page, FakeBoundingBoxProcessor(info), force=False)
        assert any("Overall bounds" in msg for msg in error_log)

        error_log.clear()
        page.override_dir.mkdir(parents=True)
        (page.override_dir / "042-overall-bounds-only.jpg").touch()
        run(page, FakeBoundingBoxProcessor(info), force=True)
        assert error_log == []

    def test_a_clean_result_logs_no_errors(self, page: Page, error_log: list[str]) -> None:
        run(page, FakeBoundingBoxProcessor(), force=False)
        assert error_log == []


class TestEachPageReportsItsOutcome:
    """The return value is a page's only route to the run summary and the exit code.

    The batch driver runs pages in worker processes, so nothing else about a page's fate
    reaches the parent.
    """

    def test_a_fresh_page(self, page: Page) -> None:
        assert run(page, FakeBoundingBoxProcessor(), force=False) == PageBoundsOutcome.OK

    def test_an_already_bounded_page(self, page: Page) -> None:
        page.already_bounded()
        assert run(page, FakeBoundingBoxProcessor(), force=False) == PageBoundsOutcome.SKIPPED

    def test_a_staged_page(self, page: Page) -> None:
        page.staged_from_home_volume()
        assert run(page, FakeBoundingBoxProcessor(), force=False) == PageBoundsOutcome.SKIPPED

    def test_a_faulty_result(self, page: Page) -> None:
        outcome = run(page, FakeBoundingBoxProcessor(UNSORTED_SEGMENT_INFO), force=False)
        assert outcome == PageBoundsOutcome.SAVED_WITH_FAULTS
        assert outcome.is_error

    def test_a_missing_source_scan(self, page: Page, error_log: list[str]) -> None:
        page.srce_file.unlink()
        outcome = run(page, FakeBoundingBoxProcessor(), force=False)
        assert outcome == PageBoundsOutcome.FAILED
        assert outcome.is_error
        assert any("042.png" in msg for msg in error_log)


class TestTheRunSummary:
    def test_no_errors(self) -> None:
        messages: list[str] = []
        handler_id = logger.add(lambda msg: messages.append(str(msg)), level="SUCCESS")
        try:
            _log_run_summary(3, [])
        finally:
            logger.remove(handler_id)
        assert len(messages) == 1
        assert "All 3 pages" in messages[0]

    def test_lists_every_error_page(self, tmp_path: Path, error_log: list[str]) -> None:
        _log_run_summary(
            5,
            [
                (tmp_path / "b" / "007.json", PageBoundsOutcome.FAILED),
                (tmp_path / "a" / "003.json", PageBoundsOutcome.SAVED_WITH_FAULTS),
            ],
        )
        assert "2 of 5 pages had errors" in error_log[0]
        assert "saved_with_faults" in error_log[1]
        assert "003.json" in error_log[1]
        assert "failed" in error_log[2]
        assert "007.json" in error_log[2]


class TestTheFantaPageList:
    """`--fanta-page` picks pages out of the batch by their Fanta volume page number."""

    def test_no_list_means_every_page(self) -> None:
        assert parse_fanta_pages("") is None
        assert parse_fanta_pages("   ") is None

    def test_single_pages(self) -> None:
        assert parse_fanta_pages("202,205") == {"202", "205"}

    def test_pages_are_zero_padded_to_match_the_filenames(self) -> None:
        assert parse_fanta_pages("5") == {"005"}
        assert parse_fanta_pages("005") == {"005"}

    def test_a_range_is_inclusive_at_both_ends(self) -> None:
        assert parse_fanta_pages("210-214") == {"210", "211", "212", "213", "214"}

    def test_a_one_page_range(self) -> None:
        assert parse_fanta_pages("210-210") == {"210"}

    def test_ranges_and_singles_mix(self) -> None:
        assert parse_fanta_pages(" 202 , 210-212 ") == {"202", "210", "211", "212"}

    def test_overlapping_pages_are_asked_for_once(self) -> None:
        assert parse_fanta_pages("210-212,211,212-213") == {"210", "211", "212", "213"}

    @pytest.mark.parametrize("fanta_pages_str", ["abc", "202-abc", "202-", "202,205-203"])
    def test_a_malformed_list_is_rejected(self, fanta_pages_str: str) -> None:
        with pytest.raises(typer.BadParameter):
            parse_fanta_pages(fanta_pages_str)

    @pytest.mark.parametrize("fanta_pages_str", ["0", "-202", "202,0-3"])
    def test_a_page_that_cannot_exist_is_rejected(self, fanta_pages_str: str) -> None:
        """To `intspan`, "-202" is the page number -202, and zero is a fine page."""
        with pytest.raises(typer.BadParameter):
            parse_fanta_pages(fanta_pages_str)


class TestSelectingThePagesToBound:
    """Which source/segments pairs a page list leaves for the batch to work on."""

    @staticmethod
    def _files(tmp_path: Path, page_nums: list[str]) -> tuple[list[Any], list[Path]]:
        srce_files = [(tmp_path / "srce" / f"{num}.png", None) for num in page_nums]
        dest_files = [tmp_path / "segments" / f"{num}.json" for num in page_nums]
        return srce_files, dest_files

    def test_no_page_list_keeps_every_page(self, tmp_path: Path) -> None:
        srce_files, dest_files = self._files(tmp_path, ["001", "002", "003"])

        page_pairs = _get_page_pairs(srce_files, dest_files, None)

        assert [dest.stem for _, dest in page_pairs] == ["001", "002", "003"]

    def test_only_the_listed_pages_are_kept(self, tmp_path: Path) -> None:
        srce_files, dest_files = self._files(tmp_path, ["001", "002", "003"])

        page_pairs = _get_page_pairs(srce_files, dest_files, {"001", "003"})

        assert [dest.stem for _, dest in page_pairs] == ["001", "003"]

    def test_the_source_page_travels_with_its_segments_file(self, tmp_path: Path) -> None:
        srce_files, dest_files = self._files(tmp_path, ["001", "002"])

        page_pairs = _get_page_pairs(srce_files, dest_files, {"002"})

        assert page_pairs == [(tmp_path / "srce" / "002.png", tmp_path / "segments" / "002.json")]

    def test_a_page_in_no_title_leaves_nothing_to_do(self, tmp_path: Path) -> None:
        srce_files, dest_files = self._files(tmp_path, ["001", "002"])

        assert _get_page_pairs(srce_files, dest_files, {"999"}) == []
