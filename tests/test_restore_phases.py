"""Tests for running a batch of pages through the restore's phases, and stopping it.

The phases run in pools of worker processes, each on a copy of its page's pipeline, so
nothing a worker does to that copy reaches the run that started it. What became of a page
has to come back in what the worker returns, and be folded into the run's picture of the
batch - and that folding is what decides, when a stop arrives, which pages are finished,
which are part way and keep their work files, and which were never begun.

The pipelines here do no restoring. Each part leaves a marker file saying it ran, which is
the only kind of evidence that survives the process boundary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from barks_comic_building.restore import batch_restore_pipeline
from barks_comic_building.restore.batch_restore_pipeline import (
    RunResult,
    _PhaseOutcome,
    _PhaseResult,
    _record_phase_result,
    _run_restore_phase,
    run_restore,
)
from barks_comic_building.restore.restore_pipeline import RestorePipeline
from barks_comic_building.restore.run_stop import StopMode, get_stop_file, request_stop

PARTS = ("do_part1", "do_part2_memory_hungry", "do_part3", "do_part4_memory_hungry")

FAIL = "fail"
ASK_FOR_STOP = "ask for the gentle stop"
ASK_FOR_STOP_NOW = "ask for the urgent stop"


class MarkerPipeline(RestorePipeline):
    """A pipeline whose parts only record that they ran, and misbehave on request."""

    def __init__(self, tmp_path: Path, page: str, behaviour: dict[str, str]) -> None:
        work_dir = tmp_path / "work"
        out_dir = tmp_path / "restored"
        for directory in (work_dir, out_dir):
            directory.mkdir(exist_ok=True)
        upscayl_file = tmp_path / f"{page}.png"
        upscayl_file.write_bytes(b"upscayled")

        super().__init__(
            work_dir,
            tmp_path / f"{page}.jpg",
            upscayl_file,
            4,
            out_dir / f"{page}.png",
            out_dir / f"{page}-4x.png",
            out_dir / f"{page}.svg",
            stop_file=get_stop_file(work_dir),
        )
        self.page = page
        self.behaviour = behaviour

    def marker(self, part: str) -> Path:
        return self.work_dir / f"{self.page}.{part}.ran"

    def parts_run(self) -> list[str]:
        return [part for part in PARTS if self.marker(part).is_file()]

    def _do(self, part: str) -> None:
        self.marker(part).touch()
        self.step_seconds[part] = 1.0

        behaviour = self.behaviour.get(part)
        if behaviour == FAIL:
            self.errors_occurred = True
            self.failed_step = part
        elif behaviour == ASK_FOR_STOP:
            request_stop(self.work_dir, StopMode.PAGES)
        elif behaviour == ASK_FOR_STOP_NOW:
            request_stop(self.work_dir, StopMode.STEP)
            self.stopped_early = True

    def do_part1(self) -> None:
        self._do("do_part1")

    def do_part2_memory_hungry(self) -> None:
        self._do("do_part2_memory_hungry")

    def do_part3(self) -> None:
        self._do("do_part3")

    def do_part4_memory_hungry(self) -> None:
        self._do("do_part4_memory_hungry")


def make_pages(tmp_path: Path, per_page: dict[str, dict[str, str]]) -> list[MarkerPipeline]:
    return [MarkerPipeline(tmp_path, page, behaviour) for page, behaviour in per_page.items()]


class TestOnePageInOnePhase:
    """What a worker does when its turn comes, and what it sends back."""

    def run(self, page: MarkerPipeline, part: str = "do_part2_memory_hungry") -> _PhaseResult:
        return _run_restore_phase(page, part, None, is_first_phase=part == PARTS[0])

    def test_a_page_runs_and_reports_its_timings(self, tmp_path: Path) -> None:
        (page,) = make_pages(tmp_path, {"110": {}})

        result = self.run(page)

        assert result.outcome is _PhaseOutcome.RAN
        assert not result.errors_occurred
        assert result.step_seconds == {"do_part2_memory_hungry": 1.0}

    def test_a_failure_comes_back_with_the_step_it_failed_at(self, tmp_path: Path) -> None:
        (page,) = make_pages(tmp_path, {"110": {"do_part2_memory_hungry": FAIL}})

        result = self.run(page)

        assert result.errors_occurred
        assert result.failed_step == "do_part2_memory_hungry"
        assert result.outcome is _PhaseOutcome.RAN

    def test_an_urgent_stop_skips_a_page_whatever_phase_it_is_in(self, tmp_path: Path) -> None:
        (page,) = make_pages(tmp_path, {"110": {}})
        request_stop(page.work_dir, StopMode.STEP)

        assert self.run(page).outcome is _PhaseOutcome.SKIPPED
        assert page.parts_run() == []

    def test_a_gentle_stop_skips_a_page_that_has_not_started(self, tmp_path: Path) -> None:
        (page,) = make_pages(tmp_path, {"110": {}})
        request_stop(page.work_dir, StopMode.PAGES)

        assert self.run(page, "do_part1").outcome is _PhaseOutcome.SKIPPED
        assert page.parts_run() == []

    def test_a_gentle_stop_lets_a_page_already_under_way_carry_on(self, tmp_path: Path) -> None:
        (page,) = make_pages(tmp_path, {"110": {}})
        request_stop(page.work_dir, StopMode.PAGES)

        assert self.run(page, "do_part3").outcome is _PhaseOutcome.RAN
        assert page.parts_run() == ["do_part3"]

    def test_a_page_that_gave_up_between_steps_says_so(self, tmp_path: Path) -> None:
        (page,) = make_pages(tmp_path, {"110": {"do_part2_memory_hungry": ASK_FOR_STOP_NOW}})

        assert self.run(page).outcome is _PhaseOutcome.STOPPED


class TestFoldingAResultBackIn:
    """The worker changed a copy, so the run's own pipeline only knows what it is told."""

    def record(
        self, page: MarkerPipeline, run: RunResult, outcome: _PhaseOutcome, *, failed: bool = False
    ) -> None:
        result = _PhaseResult(
            errors_occurred=failed,
            failed_step="smooth" if failed else None,
            step_seconds={"smooth": 154.0},
            outcome=outcome,
        )
        _record_phase_result(result, 0, page, "part 2", run)

    def test_a_failure_is_marked_on_the_runs_own_pipeline(self, tmp_path: Path) -> None:
        (page,) = make_pages(tmp_path, {"110": {}})
        run = RunResult()

        self.record(page, run, _PhaseOutcome.RAN, failed=True)

        assert page.errors_occurred
        assert page.failed_step == "smooth"
        assert run.failed == {0}
        assert run.is_settled(0)

    def test_the_timings_are_copied_back(self, tmp_path: Path) -> None:
        (page,) = make_pages(tmp_path, {"110": {}})

        self.record(page, RunResult(), _PhaseOutcome.RAN)

        assert page.step_seconds == {"smooth": 154.0}

    def test_a_page_skipped_before_it_began_is_untouched(self, tmp_path: Path) -> None:
        (page,) = make_pages(tmp_path, {"110": {}})
        run = RunResult()

        self.record(page, run, _PhaseOutcome.SKIPPED)

        assert run.untouched == {0}
        assert run.unfinished == set()

    def test_a_page_skipped_after_it_began_is_unfinished(self, tmp_path: Path) -> None:
        """It has work files from the phases behind it, and they are kept."""
        (page,) = make_pages(tmp_path, {"110": {}})
        run = RunResult()

        self.record(page, run, _PhaseOutcome.RAN)
        self.record(page, run, _PhaseOutcome.SKIPPED)

        assert run.unfinished == {0}
        assert run.untouched == set()

    def test_a_page_that_stopped_between_steps_is_unfinished(self, tmp_path: Path) -> None:
        (page,) = make_pages(tmp_path, {"110": {}})
        run = RunResult()

        self.record(page, run, _PhaseOutcome.STOPPED)

        assert run.unfinished == {0}
        assert page.stopped_early


# The pool forks, as it does in a real run, and python warns that forking a process with
# more than one thread can deadlock the child. True of the restore itself, and not what
# these tests are about.
@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
class TestAWholeBatch:
    """The four phases, in real worker processes, one page at a time.

    One worker per phase so that pages take their turns in the order they were queued,
    which is what makes it possible to say which of them a stop should have reached.
    """

    @pytest.fixture(autouse=True)
    def _one_worker_per_phase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        phases = [(name, method, 1, omp) for name, method, _, omp in batch_restore_pipeline._PHASES]  # noqa: SLF001
        monkeypatch.setattr(batch_restore_pipeline, "_PHASES", phases)

    def test_every_page_goes_through_every_phase(self, tmp_path: Path) -> None:
        pages = make_pages(tmp_path, {"110": {}, "111": {}, "112": {}})

        run = run_restore(list(pages))

        assert run == RunResult(started={0, 1, 2})
        assert all(page.parts_run() == list(PARTS) for page in pages)

    def test_a_page_that_fails_goes_no_further_and_the_rest_carry_on(self, tmp_path: Path) -> None:
        pages = make_pages(
            tmp_path, {"110": {}, "111": {"do_part2_memory_hungry": FAIL}, "112": {}}
        )

        run = run_restore(list(pages))

        assert run.failed == {1}
        assert pages[1].parts_run() == list(PARTS[:2])
        assert pages[1].errors_occurred
        assert pages[1].failed_step == "do_part2_memory_hungry"
        assert pages[0].parts_run() == list(PARTS)
        assert pages[2].parts_run() == list(PARTS)

    def test_a_gentle_stop_finishes_the_page_under_way_and_begins_no_more(
        self, tmp_path: Path
    ) -> None:
        pages = make_pages(tmp_path, {"110": {"do_part1": ASK_FOR_STOP}, "111": {}, "112": {}})

        run = run_restore(list(pages))

        assert pages[0].parts_run() == list(PARTS)
        assert run.untouched == {1, 2}
        assert run.unfinished == set()
        assert run.failed == set()
        assert pages[1].parts_run() == []
        assert pages[2].parts_run() == []

    def test_an_urgent_stop_leaves_pages_part_way_through(self, tmp_path: Path) -> None:
        pages = make_pages(
            tmp_path, {"110": {"do_part2_memory_hungry": ASK_FOR_STOP_NOW}, "111": {}, "112": {}}
        )

        run = run_restore(list(pages))

        # Every page had run part 1 by then, so all three are part way, not untouched.
        assert run.unfinished == {0, 1, 2}
        assert run.untouched == set()
        assert pages[0].parts_run() == list(PARTS[:2])
        assert pages[1].parts_run() == list(PARTS[:1])
        assert pages[2].parts_run() == list(PARTS[:1])

    def test_a_worker_that_dies_of_an_exception_fails_only_its_own_page(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pages = make_pages(tmp_path, {"110": {}, "111": {}})
        # Only the first page's marker is in the way, so only its worker raises.
        pages[0].marker("do_part3").mkdir()
        monkeypatch.setattr(Path, "touch", _touch_or_raise)

        run = run_restore(list(pages))

        assert run.failed == {0}
        assert pages[0].failed_step == "part 3"
        assert pages[1].parts_run() == list(PARTS)


_real_touch = Path.touch


def _touch_or_raise(path: Path) -> None:
    """Touch a file, raising if a directory is standing where it should go."""
    if path.is_dir():
        msg = f'"{path}" is a directory'
        raise IsADirectoryError(msg)
    _real_touch(path)
