"""Tests for a whole restore run and a whole upscale run, from titles to exit status.

`restore()` and `upscayl()` are what the command line calls. They decide which pages are
queued, what goes in the ledger, when a run gives up, and the number that becomes the
exit status - and the next run, the failure report and any script chaining the stages all
read from what they leave behind.

Nothing is restored or upscayled here. The titles are files in a temporary directory, and
the step that does the real work is replaced by one that leaves a page as that work
would: finished, failed or stopped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from barks_comic_building.restore import batch_restore_pipeline, batch_upscayl
from barks_comic_building.restore.batch_restore_pipeline import RunResult, restore
from barks_comic_building.restore.batch_upscayl import upscayl
from barks_comic_building.restore.ledger_common import (
    OUTCOME_COPIED,
    OUTCOME_FAILED,
    OUTCOME_OK,
    OUTCOME_PRESENT,
    OUTCOME_STOPPED,
)
from barks_comic_building.restore.restore_ledger import read_ledger
from barks_comic_building.restore.restore_pipeline import STEP_SMOOTH
from barks_comic_building.restore.run_stop import (
    StopMode,
    get_stop_file,
    read_stop_mode,
    request_stop,
)
from barks_comic_building.restore.upscale_image import DEFAULT_UPSCALER
from barks_comic_building.restore.upscale_ledger import read_upscale_ledger
from tests.fake_comic import (
    OLD_RECIPE_ID,
    RESTORE_RECIPE_ID,
    TITLE,
    UPSCALE_RECIPE_ID,
    VOLUME,
    FakeComic,
    as_database,
    write_png,
)

if TYPE_CHECKING:
    from pathlib import Path

    from barks_comic_building.restore.restore_pipeline import RestorePipeline
    from barks_comic_building.restore.upscale_image import Upscaler

UNTOUCHED = "untouched"


class RestoreRun:
    """A restore run over one title, with the phases replaced by the fates given."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, comic: FakeComic) -> None:
        self.comic = comic
        self.work_dir = tmp_path / "work"
        self.work_dir.mkdir()
        self.ledger_file = tmp_path / "restore-ledger.jsonl"

        self.fates: dict[str, str] = {}
        """What becomes of a page, by page. One not named here restores cleanly."""

        self.stop_during_batch: int | None = None
        """Ask for the gentle stop while this batch (counting from 1) is running."""

        self.batches: list[list[str]] = []
        """The pages each batch was handed, in the order the batches ran."""

        self.stop_seen_at_start: StopMode | None = None

        monkeypatch.setattr(batch_restore_pipeline, "run_restore", self._run_restore)

    def _run_restore(self, procs: list[RestorePipeline], _deadline: float | None) -> RunResult:
        if not self.batches:
            self.stop_seen_at_start = read_stop_mode(get_stop_file(self.work_dir))
        self.batches.append([proc.dest_restored_file.stem for proc in procs])

        result = RunResult()
        for i, proc in enumerate(procs):
            page = proc.dest_restored_file.stem
            fate = self.fates.get(page, OUTCOME_OK)
            if fate == OUTCOME_FAILED:
                proc.errors_occurred = True
                proc.failed_step = STEP_SMOOTH
                result.failed.add(i)
            elif fate == OUTCOME_STOPPED:
                proc.stopped_early = True
                result.unfinished.add(i)
            elif fate == UNTOUCHED:
                result.untouched.add(i)
            else:
                for file in proc.expected_output_files:
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(b"output")
                # As the real last step leaves it: stamped with the recipe it was made on.
                write_png(proc.dest_restored_file, {"Restore recipe id": RESTORE_RECIPE_ID})

        if self.stop_during_batch == len(self.batches):
            request_stop(self.work_dir, StopMode.PAGES)

        return result

    def run(self, *, batch_size: int = 10, force: bool = False) -> int:
        return restore(
            as_database(self.comic),
            [TITLE],
            self.work_dir,
            self.ledger_file,
            batch_size,
            use_existing_work_files=False,
            debug_color_counts=False,
            keep_work_files=False,
            force=force,
        )

    def outcomes(self) -> dict[str, str]:
        return {record.page: record.outcome for record in read_ledger(self.ledger_file).pages}


@pytest.fixture
def restore_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RestoreRun:
    """Return a run over a title with one page done and three waiting.

    110 is current. 111 was restored on an older recipe, and 112 and 113 never have been.
    """
    comic = FakeComic(tmp_path, ["110", "111", "112", "113"])
    comic.write_restored("110")
    comic.write_restored("111", OLD_RECIPE_ID)
    comic.write_upscayled("112")
    comic.write_upscayled("113")
    return RestoreRun(tmp_path, monkeypatch, comic)


class TestAWholeRestoreRun:
    def test_it_restores_what_is_waiting_and_leaves_the_rest(self, restore_run: RestoreRun) -> None:
        assert restore_run.run() == 0

        assert restore_run.batches == [["111", "112", "113"]]
        assert restore_run.outcomes() == {
            "111": OUTCOME_OK,
            "112": OUTCOME_OK,
            "113": OUTCOME_OK,
        }

    def test_every_record_says_which_title_volume_and_recipe(self, restore_run: RestoreRun) -> None:
        restore_run.run()

        ledger = read_ledger(restore_run.ledger_file)
        (run_id,) = ledger.runs
        assert {(r.title, r.volume, r.recipe_id, r.run_id) for r in ledger.pages} == {
            (TITLE, VOLUME, RESTORE_RECIPE_ID, run_id)
        }

    def test_it_returns_how_many_pages_failed(self, restore_run: RestoreRun) -> None:
        restore_run.fates = {"111": OUTCOME_FAILED, "113": OUTCOME_FAILED}

        assert restore_run.run() == 2  # noqa: PLR2004

        assert restore_run.outcomes() == {
            "111": OUTCOME_FAILED,
            "112": OUTCOME_OK,
            "113": OUTCOME_FAILED,
        }

    def test_a_page_left_part_way_by_a_stop_is_not_a_failure(self, restore_run: RestoreRun) -> None:
        restore_run.fates = {"112": OUTCOME_STOPPED, "113": UNTOUCHED}

        assert restore_run.run() == 0

        assert restore_run.outcomes() == {"111": OUTCOME_OK, "112": OUTCOME_STOPPED}

    def test_the_pages_go_through_in_batches(self, restore_run: RestoreRun) -> None:
        restore_run.run(batch_size=2)

        assert restore_run.batches == [["111", "112"], ["113"]]

    def test_failures_are_counted_across_batches(self, restore_run: RestoreRun) -> None:
        restore_run.fates = {"111": OUTCOME_FAILED, "113": OUTCOME_FAILED}

        assert restore_run.run(batch_size=1) == 2  # noqa: PLR2004

        assert len(restore_run.batches) == 3  # noqa: PLR2004

    def test_a_stop_asked_for_during_a_batch_means_no_batch_after_it(
        self, restore_run: RestoreRun
    ) -> None:
        restore_run.stop_during_batch = 1

        assert restore_run.run(batch_size=1) == 0

        assert restore_run.batches == [["111"]]
        assert restore_run.outcomes() == {"111": OUTCOME_OK}

    def test_a_stop_left_over_from_the_last_run_does_not_stop_this_one(
        self, restore_run: RestoreRun
    ) -> None:
        request_stop(restore_run.work_dir, StopMode.STEP)

        restore_run.run()

        assert restore_run.stop_seen_at_start is StopMode.NONE
        assert len(restore_run.outcomes()) == 3  # noqa: PLR2004

    def test_with_nothing_waiting_it_starts_no_run_at_all(self, restore_run: RestoreRun) -> None:
        for page in ("111", "112", "113"):
            restore_run.comic.write_restored(page)

        assert restore_run.run() == 0

        assert restore_run.batches == []
        assert not restore_run.ledger_file.exists()

    def test_forcing_puts_the_current_pages_through_again(self, restore_run: RestoreRun) -> None:
        restore_run.run(force=True)

        assert restore_run.batches == [["110", "111", "112", "113"]]

    def test_a_second_run_finds_the_first_ones_pages_done(self, restore_run: RestoreRun) -> None:
        """What the first run wrote is what makes its pages current to the second."""
        restore_run.fates = {"112": OUTCOME_FAILED}
        restore_run.run()

        restore_run.fates = {}
        restore_run.batches.clear()
        restore_run.run()

        assert restore_run.batches == [["112"]]


class TestATitleThatIsNotAComic:
    """An article or a cover gallery is copied through, not restored."""

    @pytest.fixture
    def restore_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RestoreRun:
        comic = FakeComic(tmp_path, ["201", "202"])
        comic.write_srce("201")
        comic.write_srce("202")
        write_png(comic.restored("202"))
        monkeypatch.setattr(batch_restore_pipeline, "is_non_comic_title", lambda _title: True)
        return RestoreRun(tmp_path, monkeypatch, comic)

    def test_its_pages_are_copied_and_none_is_restored(self, restore_run: RestoreRun) -> None:
        assert restore_run.run() == 0

        assert restore_run.batches == []
        assert restore_run.comic.restored("201").is_file()

    def test_the_ledger_tells_a_page_copied_from_one_already_there(
        self, restore_run: RestoreRun
    ) -> None:
        restore_run.run()

        assert restore_run.outcomes() == {"201": OUTCOME_COPIED, "202": OUTCOME_PRESENT}

    def test_a_page_already_there_is_not_copied_over(self, restore_run: RestoreRun) -> None:
        before = restore_run.comic.restored("202").read_bytes()

        restore_run.run()

        assert restore_run.comic.restored("202").read_bytes() == before


class UpscaleRun:
    """An upscale run over one title, with a stand-in for the upscaler.

    The stand-in works on every page except the ones it is told to fail on.
    """

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, comic: FakeComic) -> None:
        self.comic = comic
        self.ledger_file = tmp_path / "upscale-ledger.jsonl"
        self.failing_pages: set[str] = set()
        self.pages_tried: list[str] = []
        self.is_usable = True

        monkeypatch.setattr(batch_upscayl, "upscale_image_file", self._upscale_image_file)
        monkeypatch.setattr(batch_upscayl, "check_upscaler_is_usable", self._check_is_usable)

    def _check_is_usable(self, _upscaler: Upscaler, _scale: int) -> None:
        if not self.is_usable:
            msg = "waifu2x is not installed"
            raise FileNotFoundError(msg)

    def _upscale_image_file(
        self, in_file: Path, out_file: Path, _scale: int, _upscaler: Upscaler
    ) -> None:
        self.pages_tried.append(in_file.stem)
        if in_file.stem in self.failing_pages:
            msg = "the GPU ran out of memory"
            raise RuntimeError(msg)

        self.comic.write_upscayled(in_file.stem)
        assert out_file == self.comic.upscayl(in_file.stem)

    def run(self, *, force: bool = False) -> int:
        return upscayl(
            as_database(self.comic), [TITLE], DEFAULT_UPSCALER, self.ledger_file, force=force
        )

    def outcomes(self) -> dict[str, str]:
        ledger = read_upscale_ledger(self.ledger_file)
        return {record.page: record.outcome for record in ledger.pages}


@pytest.fixture
def upscale_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> UpscaleRun:
    """Return a run over a title with one page done and four waiting.

    110 is current. 111 was upscayled on an older recipe, and 112 to 114 never have been.
    """
    comic = FakeComic(tmp_path, ["110", "111", "112", "113", "114"])
    comic.write_upscayled("110")
    comic.write_upscayled("111", OLD_RECIPE_ID)
    for page in ("112", "113", "114"):
        comic.write_srce(page)
    return UpscaleRun(tmp_path, monkeypatch, comic)


class TestAWholeUpscaleRun:
    def test_it_upscayls_what_is_waiting_and_leaves_the_rest(self, upscale_run: UpscaleRun) -> None:
        assert upscale_run.run() == 0

        assert upscale_run.pages_tried == ["111", "112", "113", "114"]
        assert set(upscale_run.outcomes().values()) == {OUTCOME_OK}

    def test_every_record_says_which_title_volume_and_recipe(self, upscale_run: UpscaleRun) -> None:
        upscale_run.run()

        ledger = read_upscale_ledger(upscale_run.ledger_file)
        (run_id,) = ledger.runs
        assert {(r.title, r.volume, r.recipe_id, r.run_id) for r in ledger.pages} == {
            (TITLE, VOLUME, UPSCALE_RECIPE_ID, run_id)
        }

    def test_one_bad_page_is_recorded_and_the_run_carries_on(self, upscale_run: UpscaleRun) -> None:
        upscale_run.failing_pages = {"112"}

        assert upscale_run.run() == 1

        assert upscale_run.pages_tried == ["111", "112", "113", "114"]
        records = {r.page: r for r in read_upscale_ledger(upscale_run.ledger_file).pages}
        assert records["112"].outcome == OUTCOME_FAILED
        assert records["112"].error == "the GPU ran out of memory"
        assert records["113"].outcome == OUTCOME_OK
        assert records["113"].error is None

    def test_it_gives_up_when_pages_fail_one_after_another(
        self, upscale_run: UpscaleRun, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(batch_upscayl, "MAX_CONSECUTIVE_FAILURES", 2)
        upscale_run.failing_pages = {"112", "113"}

        num_not_done = upscale_run.run()

        # 114 was never reached, and is as much not done as the two that failed.
        assert upscale_run.pages_tried == ["111", "112", "113"]
        assert num_not_done == 3  # noqa: PLR2004
        assert "114" not in upscale_run.outcomes()

    def test_a_page_that_works_ends_a_run_of_failures(
        self, upscale_run: UpscaleRun, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(batch_upscayl, "MAX_CONSECUTIVE_FAILURES", 2)
        upscale_run.failing_pages = {"111", "113"}

        assert upscale_run.run() == 2  # noqa: PLR2004

        assert upscale_run.pages_tried == ["111", "112", "113", "114"]

    def test_with_nothing_waiting_it_starts_no_run_at_all(self, upscale_run: UpscaleRun) -> None:
        for page in ("111", "112", "113", "114"):
            upscale_run.comic.write_upscayled(page)

        assert upscale_run.run() == 0

        assert upscale_run.pages_tried == []
        assert not upscale_run.ledger_file.exists()

    def test_forcing_puts_the_current_pages_through_again(self, upscale_run: UpscaleRun) -> None:
        upscale_run.run(force=True)

        assert upscale_run.pages_tried == ["110", "111", "112", "113", "114"]

    def test_a_second_run_finds_the_first_ones_pages_done(self, upscale_run: UpscaleRun) -> None:
        upscale_run.failing_pages = {"113"}
        upscale_run.run()

        upscale_run.failing_pages = set()
        upscale_run.pages_tried.clear()
        upscale_run.run()

        assert upscale_run.pages_tried == ["113"]

    def test_an_upscaler_that_cannot_run_stops_the_run_before_any_page(
        self, upscale_run: UpscaleRun
    ) -> None:
        """One failure record per queued page would look like a run that completed."""
        upscale_run.is_usable = False

        with pytest.raises(FileNotFoundError):
            upscale_run.run()

        assert upscale_run.pages_tried == []
        assert not upscale_run.ledger_file.exists()

    def test_a_title_that_is_not_a_comic_is_not_upscayled(
        self, upscale_run: UpscaleRun, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(batch_upscayl, "is_non_comic_title", lambda _title: True)

        assert upscale_run.run() == 0

        assert upscale_run.pages_tried == []
