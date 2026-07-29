"""Tests for the record of what the restore did.

The ledger is written across weeks by a process that will be killed, resumed and killed
again, so the properties worth testing are the ones that survive that: a half written last
line must not cost the other thousands of records, the newest attempt at a page must win
over its earlier failures, and the timings the estimate is built from must not be polluted
by pages that failed part way through.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from barks_comic_building.restore.restore_ledger import (
    LEDGER_SCHEMA,
    OUTCOME_COPIED,
    OUTCOME_FAILED,
    OUTCOME_OK,
    OUTCOME_PRESENT,
    LedgerWriter,
    read_ledger,
)
from barks_comic_building.restore.restore_recipe import get_current_recipe

if TYPE_CHECKING:
    from pathlib import Path

WORKERS = {"part 2": 6, "part 4": 4}

# Named so the assertions read as "both of them" rather than as a bare literal.
TWO = 2


@pytest.fixture
def ledger_file(tmp_path: Path) -> Path:
    return tmp_path / "restore-ledger.jsonl"


def write_pages(ledger_file: Path, pages: list[tuple[str, str, float]]) -> None:
    """Append one run's worth of page records: (page, outcome, total_seconds)."""
    recipe = get_current_recipe(4, do_palette_snap=True)
    with LedgerWriter(ledger_file, recipe, WORKERS) as writer:
        for page, outcome, seconds in pages:
            writer.write_page(
                title="Camp Counselor",
                volume=9,
                page=page,
                outcome=outcome,
                started="2026-07-29T12:00:00+10:00",
                total_seconds=seconds,
                step_seconds={"smooth": seconds / 2},
                failed_step="smooth" if outcome == OUTCOME_FAILED else None,
            )


class TestRoundTrip:
    def test_a_run_and_its_pages_come_back(self, ledger_file: Path) -> None:
        write_pages(ledger_file, [("110", OUTCOME_OK, 270.0)])

        ledger = read_ledger(ledger_file)

        assert len(ledger.runs) == 1
        assert len(ledger.pages) == 1
        assert ledger.pages[0].page == "110"
        assert ledger.pages[0].is_ok

    def test_the_recipe_expands_from_its_id(self, ledger_file: Path) -> None:
        """A ledger is self contained.

        A page names its recipe by id; the run record in the same file holds the settings.
        """
        write_pages(ledger_file, [("110", OUTCOME_OK, 270.0)])

        ledger = read_ledger(ledger_file)
        recipe = ledger.recipe_for(ledger.pages[0].recipe_id)

        assert recipe is not None
        assert recipe == get_current_recipe(4, do_palette_snap=True)

    def test_appending_keeps_earlier_runs(self, ledger_file: Path) -> None:
        write_pages(ledger_file, [("110", OUTCOME_OK, 270.0)])
        write_pages(ledger_file, [("111", OUTCOME_OK, 280.0)])

        ledger = read_ledger(ledger_file)

        assert len(ledger.runs) == TWO
        assert [p.page for p in ledger.pages] == ["110", "111"]

    def test_a_missing_ledger_reads_as_empty(self, tmp_path: Path) -> None:
        ledger = read_ledger(tmp_path / "never-written.jsonl")

        assert ledger.pages == []


class TestSurvivesBeingKilled:
    def test_a_truncated_last_line_is_skipped(self, ledger_file: Path) -> None:
        """What a kill -9 mid write leaves behind."""
        write_pages(ledger_file, [("110", OUTCOME_OK, 270.0), ("111", OUTCOME_OK, 280.0)])
        with ledger_file.open("a") as f:
            f.write('{"type":"page","schema":1,"title":"Camp Cou')

        ledger = read_ledger(ledger_file)

        assert [p.page for p in ledger.pages] == ["110", "111"]

    def test_a_corrupt_line_in_the_middle_costs_only_itself(self, ledger_file: Path) -> None:
        write_pages(ledger_file, [("110", OUTCOME_OK, 270.0)])
        lines = ledger_file.read_text().splitlines()
        lines.insert(1, "}}} not json {{{")
        ledger_file.write_text("\n".join(lines) + "\n")

        write_pages(ledger_file, [("111", OUTCOME_OK, 280.0)])

        ledger = read_ledger(ledger_file)

        assert [p.page for p in ledger.pages] == ["110", "111"]

    def test_a_newer_schema_is_refused_rather_than_misread(self, ledger_file: Path) -> None:
        write_pages(ledger_file, [("110", OUTCOME_OK, 270.0)])
        with ledger_file.open("a") as f:
            f.write(f'{{"type":"page","schema":{LEDGER_SCHEMA + 1},"title":"T","page":"1"}}\n')

        ledger = read_ledger(ledger_file)

        assert [p.page for p in ledger.pages] == ["110"]

    def test_blank_lines_are_ignored(self, ledger_file: Path) -> None:
        write_pages(ledger_file, [("110", OUTCOME_OK, 270.0)])
        with ledger_file.open("a") as f:
            f.write("\n\n")

        assert len(read_ledger(ledger_file).pages) == 1


class TestTimings:
    def test_failed_pages_do_not_pollute_the_estimate(self, ledger_file: Path) -> None:
        """Only successful pages count towards the estimate.

        A page that died in its first step would drag the mean down and understate the run
        left to do.
        """
        write_pages(
            ledger_file,
            [("110", OUTCOME_OK, 300.0), ("111", OUTCOME_FAILED, 10.0), ("112", OUTCOME_OK, 200.0)],
        )

        stats = read_ledger(ledger_file).timing_stats()

        assert stats is not None
        assert stats.count == TWO
        assert stats.mean_seconds == pytest.approx(250.0)

    def test_timings_can_be_restricted_to_one_recipe(self, ledger_file: Path) -> None:
        """Timings can be restricted to one recipe.

        Pages made under different settings cost different amounts, so only the current
        recipe predicts what the next page will take.
        """
        write_pages(ledger_file, [("110", OUTCOME_OK, 300.0)])
        recipe_id = read_ledger(ledger_file).pages[0].recipe_id

        assert read_ledger(ledger_file).timing_stats(recipe_id) is not None
        assert read_ledger(ledger_file).timing_stats("no-such-recipe") is None

    def test_no_successful_pages_gives_no_stats(self, ledger_file: Path) -> None:
        write_pages(ledger_file, [("110", OUTCOME_FAILED, 10.0)])

        assert read_ledger(ledger_file).timing_stats() is None


class TestLatestByPage:
    def test_a_later_attempt_replaces_an_earlier_one(self, ledger_file: Path) -> None:
        """A page that failed and was then redone is finished, not failed."""
        write_pages(ledger_file, [("110", OUTCOME_FAILED, 10.0)])
        write_pages(ledger_file, [("110", OUTCOME_OK, 270.0)])

        latest = read_ledger(ledger_file).latest_by_page()

        assert len(latest) == 1
        assert latest["Camp Counselor", "110"].is_ok

    def test_pages_are_keyed_by_title_and_page(self, ledger_file: Path) -> None:
        write_pages(ledger_file, [("110", OUTCOME_OK, 270.0), ("111", OUTCOME_OK, 280.0)])

        assert len(read_ledger(ledger_file).latest_by_page()) == TWO


class TestWriterLifecycle:
    def test_writing_outside_the_context_manager_is_refused(self, ledger_file: Path) -> None:
        writer = LedgerWriter(ledger_file, get_current_recipe(4, do_palette_snap=True), WORKERS)

        with pytest.raises(RuntimeError, match="context manager"):
            writer.write_page(
                title="T",
                volume=9,
                page="1",
                outcome=OUTCOME_OK,
                started="2026-07-29T12:00:00+10:00",
                total_seconds=1.0,
                step_seconds={},
            )

    def test_records_are_flushed_as_they_are_written(self, ledger_file: Path) -> None:
        """The ledger has to be readable from another process while a run is going."""
        recipe = get_current_recipe(4, do_palette_snap=True)
        with LedgerWriter(ledger_file, recipe, WORKERS) as writer:
            writer.write_page(
                title="T",
                volume=9,
                page="1",
                outcome=OUTCOME_OK,
                started="2026-07-29T12:00:00+10:00",
                total_seconds=1.0,
                step_seconds={},
            )

            assert len(read_ledger(ledger_file).pages) == 1


class TestStatsAreOverOneSetOfPages:
    def test_an_untimed_page_is_left_out_of_the_step_means_too(self, ledger_file: Path) -> None:
        """The step table reports itself as being over `count` pages, so it has to be.

        A page with no total counts towards neither figure; counting its steps but not its
        total would put the two on different sets of pages.
        """
        write_pages(ledger_file, [("110", OUTCOME_OK, 300.0), ("111", OUTCOME_OK, 0.0)])

        stats = read_ledger(ledger_file).timing_stats()

        assert stats is not None
        assert stats.count == 1
        assert stats.step_mean_seconds["smooth"] == pytest.approx(150.0)


class TestCopiedPages:
    """Non-comic pages are copied through rather than restored, and recorded as such.

    They read as fine, since the page is there and correct, but they are not evidence of
    what restoring costs: a file copy takes a fraction of a second where a restore takes
    minutes.
    """

    def write_copy(
        self, ledger_file: Path, page: str, seconds: float, outcome: str = OUTCOME_COPIED
    ) -> None:
        recipe = get_current_recipe(4, do_palette_snap=True)
        with LedgerWriter(ledger_file, recipe, WORKERS) as writer:
            writer.write_page(
                title="Silent Night",
                volume=9,
                page=page,
                outcome=outcome,
                started="2026-07-29T12:00:00+10:00",
                total_seconds=seconds,
                step_seconds={},
            )

    def test_a_copied_page_reads_as_fine(self, ledger_file: Path) -> None:
        self.write_copy(ledger_file, "201", 0.2)

        assert read_ledger(ledger_file).pages[0].is_ok

    def test_a_copied_page_is_not_counted_as_a_restore_timing(self, ledger_file: Path) -> None:
        """Otherwise a volume of one-pagers would shorten every estimate after it."""
        write_pages(ledger_file, [("110", OUTCOME_OK, 300.0)])
        self.write_copy(ledger_file, "201", 0.2)

        stats = read_ledger(ledger_file).timing_stats()

        assert stats is not None
        assert stats.count == 1
        assert stats.mean_seconds == pytest.approx(300.0)

    def test_copies_alone_give_no_timings(self, ledger_file: Path) -> None:
        self.write_copy(ledger_file, "201", 0.2)

        assert read_ledger(ledger_file).timing_stats() is None

    def test_a_page_that_was_already_there_reads_as_fine(self, ledger_file: Path) -> None:
        """Not a failure, and listing it as one would bury the real failures."""
        self.write_copy(ledger_file, "201", 0.0, OUTCOME_PRESENT)

        record = read_ledger(ledger_file).pages[0]

        assert record.is_ok
        assert record.outcome == OUTCOME_PRESENT

    def test_a_page_that_was_already_there_is_not_a_timing_either(self, ledger_file: Path) -> None:
        """It records that a run looked at the page, not that it did work on it."""
        write_pages(ledger_file, [("110", OUTCOME_OK, 300.0)])
        self.write_copy(ledger_file, "201", 0.3, OUTCOME_PRESENT)

        stats = read_ledger(ledger_file).timing_stats()

        assert stats is not None
        assert stats.count == 1
        assert stats.mean_seconds == pytest.approx(300.0)
