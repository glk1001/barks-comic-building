"""Tests for what a batch says became of its pages when a run is stopped or pages fail.

A run that is stopped and a page that fails are both ordinary events in a job this long,
and they overlap: a stop lands in a batch where something has already failed. The record
of that batch is what the next run and the failure report are read from, so a page filed
under the wrong outcome is either redone for nothing or never looked at again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from barks_comic_building.restore import batch_restore_pipeline
from barks_comic_building.restore.batch_restore_pipeline import (
    RunResult,
    _PageJob,
    _run_batch,
    _stop_at_deadline,
    _Tally,
)
from barks_comic_building.restore.restore_ledger import (
    OUTCOME_FAILED,
    OUTCOME_OK,
    OUTCOME_STOPPED,
    LedgerWriter,
    read_ledger,
)
from barks_comic_building.restore.restore_pipeline import STEP_SMOOTH, RestorePipeline
from barks_comic_building.restore.restore_recipe import get_current_recipe
from barks_comic_building.restore.restore_status import print_failures
from barks_comic_building.restore.run_stop import (
    StopMode,
    get_stop_file,
    read_stop_mode,
    request_stop,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

    from barks_comic_building.restore.restore_ledger import PageRecord


def make_pipeline(tmp_path: Path, page: str) -> RestorePipeline:
    """Build a pipeline for one page, with the directories and input it validates."""
    work_dir = tmp_path / "work"
    out_dir = tmp_path / "restored"
    svg_dir = tmp_path / "svg"
    for directory in (work_dir, out_dir, svg_dir):
        directory.mkdir(exist_ok=True)

    upscayl_file = tmp_path / f"{page}.png"
    upscayl_file.write_bytes(b"upscayled")

    return RestorePipeline(
        work_dir,
        tmp_path / f"{page}.jpg",
        upscayl_file,
        4,
        out_dir / f"{page}.png",
        out_dir / f"{page}-4x.png",
        svg_dir / f"{page}.svg",
        do_palette_snap=False,
    )


def fake_run_restore(
    fates: dict[str, str],
) -> Callable[[list[RestorePipeline], float | None], RunResult]:
    """Return a stand-in for `run_restore` under which the pages meet the given fates.

    It does what the real one does to the parent's pipelines: a failed page is marked on
    its own pipeline as its result comes back, and a page that ran to the end has every
    output on disk.
    """

    def run_restore(procs: list[RestorePipeline], _deadline: float | None) -> RunResult:
        result = RunResult()
        for i, (proc, fate) in enumerate(zip(procs, fates.values(), strict=True)):
            if fate == OUTCOME_FAILED:
                proc.errors_occurred = True
                proc.failed_step = STEP_SMOOTH
                result.failed.add(i)
            elif fate == OUTCOME_STOPPED:
                proc.stopped_early = True
                result.unfinished.add(i)
            elif fate == "untouched":
                result.untouched.add(i)
            else:
                for file in proc.expected_output_files:
                    file.write_bytes(b"output")
        return result

    return run_restore


def run_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fates: dict[str, str],
) -> tuple[dict[str, PageRecord], list[RestorePipeline]]:
    """Run a batch whose pages meet the given fates, without restoring anything.

    The stand-in for `run_restore` does what the real one does to the parent's pipelines:
    a failed page is marked on its own pipeline as its result comes back, and a page that
    ran to the end has every output on disk.
    """
    pipelines = [make_pipeline(tmp_path, page) for page in fates]

    monkeypatch.setattr(batch_restore_pipeline, "run_restore", fake_run_restore(fates))

    jobs = [
        _PageJob(pipeline, "Camp Counselor", 9, page)
        for pipeline, page in zip(pipelines, fates, strict=True)
    ]
    ledger_file = tmp_path / "restore-ledger.jsonl"
    recipe = get_current_recipe(4, do_palette_snap=False)
    with LedgerWriter(ledger_file, recipe, {"part 2": 6}) as ledger:
        _run_batch(jobs, ledger, 0, len(jobs), 0.0, None, keep_work_files=False)

    return {record.page: record for record in read_ledger(ledger_file).pages}, pipelines


class TestWhatABatchReturns:
    """The run's closing line and its exit code are both built from this."""

    def test_the_tally_says_how_each_attempted_page_came_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fates = {
            "110": OUTCOME_STOPPED,
            "111": OUTCOME_FAILED,
            "112": OUTCOME_OK,
            "113": OUTCOME_OK,
            "114": "untouched",
        }
        pipelines = [make_pipeline(tmp_path, page) for page in fates]
        monkeypatch.setattr(batch_restore_pipeline, "run_restore", fake_run_restore(fates))
        jobs = [
            _PageJob(pipeline, "Camp Counselor", 9, page)
            for pipeline, page in zip(pipelines, fates, strict=True)
        ]

        recipe = get_current_recipe(4, do_palette_snap=False)
        with LedgerWriter(tmp_path / "restore-ledger.jsonl", recipe, {"part 2": 6}) as ledger:
            tally = _run_batch(jobs, ledger, 0, len(jobs), 0.0, None, keep_work_files=False)

        assert tally == _Tally(num_ok=2, num_failed=1, num_stopped=1)
        assert tally.num_attempted == len(fates) - 1

    def test_tallies_add_up_across_batches(self) -> None:
        total = _Tally(num_ok=60, num_failed=4).plus(_Tally(num_ok=1, num_stopped=3))

        assert total == _Tally(num_ok=61, num_failed=4, num_stopped=3)
        assert "61 restored, 4 failed, 3 left part way through" in total.describe


class TestWhatABatchRecords:
    def test_a_page_that_restored_cleanly_is_not_blamed_for_the_page_before_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stopped page ahead of a failed one used to shift the blame along by one.

        The failures were passed by their position in the batch, to a list the stopped
        pages had been taken out of.
        """
        records, pipelines = run_batch(
            tmp_path,
            monkeypatch,
            {
                "110": OUTCOME_STOPPED,
                "111": OUTCOME_FAILED,
                "112": OUTCOME_OK,
                "113": OUTCOME_OK,
            },
        )

        assert {page: record.outcome for page, record in records.items()} == {
            "110": OUTCOME_STOPPED,
            "111": OUTCOME_FAILED,
            "112": OUTCOME_OK,
            "113": OUTCOME_OK,
        }
        assert records["111"].failed_step == STEP_SMOOTH
        assert not pipelines[2].errors_occurred

    def test_a_page_never_begun_is_not_recorded_at_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records, _ = run_batch(
            tmp_path,
            monkeypatch,
            {"110": "untouched", "111": OUTCOME_FAILED, "112": OUTCOME_OK},
        )

        assert {page: record.outcome for page, record in records.items()} == {
            "111": OUTCOME_FAILED,
            "112": OUTCOME_OK,
        }

    def test_a_page_that_ran_but_left_an_output_out_has_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def lose_an_output(procs: list[RestorePipeline]) -> None:
            procs[0].png_of_svg_file.unlink()
            real_check(procs)

        real_check = batch_restore_pipeline.check_for_errors
        monkeypatch.setattr(batch_restore_pipeline, "check_for_errors", lose_an_output)

        records, pipelines = run_batch(tmp_path, monkeypatch, {"110": OUTCOME_OK})

        assert records["110"].outcome == OUTCOME_FAILED
        assert pipelines[0].errors_occurred

    def test_only_a_finished_page_has_its_work_files_cleaned_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kept: list[RestorePipeline] = []
        monkeypatch.setattr(batch_restore_pipeline, "_clean_up_work_files", kept.append)

        _, pipelines = run_batch(
            tmp_path,
            monkeypatch,
            {"110": OUTCOME_STOPPED, "111": OUTCOME_FAILED, "112": OUTCOME_OK},
        )

        assert kept == [pipelines[2]]


class TestTheDeadline:
    """Reaching --stop-after makes the gentle stop, and leaves anybody else's alone."""

    def test_it_asks_for_started_pages_to_finish(self, tmp_path: Path) -> None:
        _stop_at_deadline(get_stop_file(tmp_path))

        assert read_stop_mode(get_stop_file(tmp_path)) is StopMode.PAGES

    def test_it_does_not_turn_a_gentle_stop_into_an_urgent_one(self, tmp_path: Path) -> None:
        """Or pages the log says will finish are cut short after their current step."""
        request_stop(tmp_path)

        _stop_at_deadline(get_stop_file(tmp_path))

        assert read_stop_mode(get_stop_file(tmp_path)) is StopMode.PAGES

    def test_it_does_not_relax_an_urgent_stop(self, tmp_path: Path) -> None:
        request_stop(tmp_path, StopMode.STEP)

        _stop_at_deadline(get_stop_file(tmp_path))

        assert read_stop_mode(get_stop_file(tmp_path)) is StopMode.STEP

    def test_a_run_that_cannot_be_stopped_is_left_alone(self) -> None:
        _stop_at_deadline(None)


class TestTheFailureReport:
    def write(self, ledger_file: Path, pages: dict[str, str]) -> None:
        recipe = get_current_recipe(4, do_palette_snap=True)
        with LedgerWriter(ledger_file, recipe, {"part 2": 6}) as writer:
            for page, outcome in pages.items():
                writer.write_page(
                    title="Camp Counselor",
                    volume=9,
                    page=page,
                    outcome=outcome,
                    started="2026-07-29T12:00:00+10:00",
                    total_seconds=270.0,
                    step_seconds={},
                    failed_step=STEP_SMOOTH if outcome == OUTCOME_FAILED else None,
                )

    def test_a_stopped_page_is_not_listed_as_a_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_file = tmp_path / "restore-ledger.jsonl"
        self.write(
            ledger_file,
            {"110": OUTCOME_STOPPED, "111": OUTCOME_FAILED, "112": OUTCOME_OK},
        )

        print_failures(read_ledger(ledger_file))

        out = capsys.readouterr().out
        assert "1 failed page(s)" in out
        assert "111" in out
        assert "110" not in out
        assert "unknown" not in out

    def test_a_run_that_was_only_stopped_has_no_failures(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_file = tmp_path / "restore-ledger.jsonl"
        self.write(ledger_file, {"110": OUTCOME_STOPPED, "111": OUTCOME_STOPPED})

        print_failures(read_ledger(ledger_file))

        assert "No failed pages recorded." in capsys.readouterr().out
