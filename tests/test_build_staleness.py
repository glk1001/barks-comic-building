"""Tests for the staleness verdicts the build integrity report is built from.

These predicates decide whether a built artifact predates something it was built from.
Two failures matter and both are silent. A verdict that can never fire reports a clean
tree forever - which is exactly what this module's dead twin did for the whole of this
repo's history. A verdict that fires on everything is no better, and is what an unknown
reference would produce if it compared against zero instead of declining to answer. Both
directions are pinned here.

The rest is the existence-versus-staleness split that the two former implementations
disagreed about: one called a missing zip not-stale, the other called it missing, and one
would `stat()` a symlink that was not there and raise.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from barks_comic_building.build.comics_integrity import (
    ComicsIntegrityChecker,
    OutOfDateErrors,
)
from barks_comic_building.build.utils import (
    MaxTimestamp,
    ZipOutOfDateErrors,
    check_zip_freshness,
    check_zip_symlink_freshness,
    fold_max,
    get_file_out_of_date_with_other_file_msg,
    is_stale,
)

if TYPE_CHECKING:
    from barks_fantagraphics.comic_book import ComicBook
    from barks_fantagraphics.comics_database import ComicsDatabase

# Fixed epoch seconds, far enough apart that no filesystem timestamp granularity can
# blur the ordering.
OLD = 1_700_000_000.0
NEW = 1_800_000_000.0
NEWER = 1_900_000_000.0

# `get_restored_srce_dependencies` uses -1 for a pipeline stage whose file is not on disk.
MISSING_STAGE = -1.0

# The prefix every finding in the report carries.
ERROR_PREFIX = "ERROR: "


def touch_at(path: Path, timestamp: float) -> Path:
    """Create a file with a known mtime, making its parents as needed.

    Args:
        path: The file to create.
        timestamp: The mtime to give it.

    Returns:
        The file.

    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, (timestamp, timestamp))

    return path


class TestIsStale:
    def test_an_artifact_older_than_its_input_is_stale(self) -> None:
        assert is_stale(OLD, MaxTimestamp(Path("srce.png"), NEW))

    def test_an_artifact_newer_than_its_input_is_not(self) -> None:
        assert not is_stale(NEW, MaxTimestamp(Path("srce.png"), OLD))

    def test_an_artifact_exactly_as_old_as_its_input_is_not(self) -> None:
        # Built in the same second as its source. Reporting this would make every fast
        # build look stale.
        assert not is_stale(NEW, MaxTimestamp(Path("srce.png"), NEW))

    def test_an_unknown_reference_is_never_stale(self) -> None:
        # The guard against the failure this whole module exists for, inverted: a check
        # that could not determine its inputs must report nothing, not everything.
        assert not is_stale(OLD, None)


class TestFoldMax:
    def test_the_first_file_becomes_the_maximum(self) -> None:
        assert fold_max(None, Path("a.png"), OLD) == MaxTimestamp(Path("a.png"), OLD)

    def test_a_newer_file_takes_over(self) -> None:
        current = MaxTimestamp(Path("a.png"), OLD)

        assert fold_max(current, Path("b.png"), NEW) == MaxTimestamp(Path("b.png"), NEW)

    def test_an_older_file_does_not(self) -> None:
        current = MaxTimestamp(Path("a.png"), NEW)

        assert fold_max(current, Path("b.png"), OLD) == current

    def test_an_equally_new_file_leaves_the_incumbent(self) -> None:
        current = MaxTimestamp(Path("a.png"), NEW)

        assert fold_max(current, Path("b.png"), NEW) == current

    def test_the_missing_stage_sentinel_never_becomes_the_maximum(self) -> None:
        # A file that is not on disk is a finding of its own. Letting -1 win would also
        # make the maximum go backwards, which would silently un-stale everything after.
        assert fold_max(None, Path("gone.png"), MISSING_STAGE) is None

        current = MaxTimestamp(Path("a.png"), OLD)
        assert fold_max(current, Path("gone.png"), MISSING_STAGE) == current


class TestZipFreshness:
    def test_a_missing_zip_is_missing_and_nothing_else(self, tmp_path: Path) -> None:
        # The disagreement between the two former implementations: one graded a missing
        # zip as not-stale, the other as missing. Missing wins, and it is the *only*
        # finding - also flagging it out of date would double-count one fault.
        errors = check_zip_freshness(tmp_path / "gone.cbz", MaxTimestamp(Path("s"), NEWER), None)

        assert errors.missing
        assert not errors.out_of_date_wrt_srce
        assert not errors.out_of_date_wrt_dest

    def test_a_zip_newer_than_everything_is_clean(self, tmp_path: Path) -> None:
        zip_file = touch_at(tmp_path / "comic.cbz", NEWER)

        errors = check_zip_freshness(
            zip_file, MaxTimestamp(Path("s"), OLD), MaxTimestamp(Path("d"), NEW)
        )

        assert not errors.missing
        assert not errors.out_of_date_wrt_srce
        assert not errors.out_of_date_wrt_dest

    def test_a_zip_older_than_its_sources_is_stale(self, tmp_path: Path) -> None:
        zip_file = touch_at(tmp_path / "comic.cbz", OLD)

        errors = check_zip_freshness(zip_file, MaxTimestamp(Path("s"), NEW), None)

        assert errors.out_of_date_wrt_srce
        assert not errors.out_of_date_wrt_dest

    def test_a_zip_older_than_its_dest_pages_is_stale(self, tmp_path: Path) -> None:
        zip_file = touch_at(tmp_path / "comic.cbz", OLD)

        errors = check_zip_freshness(zip_file, None, MaxTimestamp(Path("d"), NEW))

        assert errors.out_of_date_wrt_dest
        assert not errors.out_of_date_wrt_srce

    def test_a_zip_with_no_known_inputs_is_clean(self, tmp_path: Path) -> None:
        zip_file = touch_at(tmp_path / "comic.cbz", OLD)

        errors = check_zip_freshness(zip_file, None, None)

        assert not errors.out_of_date_wrt_srce
        assert not errors.out_of_date_wrt_dest


class TestZipSymlinkFreshness:
    def test_a_missing_symlink_is_missing_and_does_not_raise(self, tmp_path: Path) -> None:
        # The old `symlink_is_out_of_date_wrt_dest` had no existence check at all, so it
        # reached `get_timestamp` and raised FileNotFoundError out of a predicate.
        errors = check_zip_symlink_freshness(
            tmp_path / "gone.cbz", ZipOutOfDateErrors(), MaxTimestamp(Path("d"), NEWER)
        )

        assert errors.missing
        assert not errors.out_of_date_wrt_zip
        assert not errors.out_of_date_wrt_dest

    def test_a_dangling_symlink_is_graded_on_its_own_age(self, tmp_path: Path) -> None:
        # `get_timestamp` uses lstat, so a link whose target is gone still grades. It is
        # the link's own age that decides whether it needs recreating.
        zip_file = touch_at(tmp_path / "comic.cbz", NEW)
        symlink = tmp_path / "series" / "comic.cbz"
        symlink.parent.mkdir(parents=True, exist_ok=True)
        symlink.symlink_to(tmp_path / "vanished.cbz")
        os.utime(symlink, (OLD, OLD), follow_symlinks=False)

        errors = check_zip_symlink_freshness(
            symlink, check_zip_freshness(zip_file, None, None), None
        )

        assert not errors.missing
        assert errors.out_of_date_wrt_zip

    def test_a_symlink_older_than_the_zip_is_stale(self, tmp_path: Path) -> None:
        zip_file = touch_at(tmp_path / "comic.cbz", NEW)
        symlink = tmp_path / "series" / "comic.cbz"
        symlink.parent.mkdir(parents=True, exist_ok=True)
        symlink.symlink_to(zip_file)
        os.utime(symlink, (OLD, OLD), follow_symlinks=False)

        errors = check_zip_symlink_freshness(
            symlink, check_zip_freshness(zip_file, None, None), None
        )

        assert errors.out_of_date_wrt_zip

    def test_a_missing_zip_is_no_reference_for_the_symlink(self, tmp_path: Path) -> None:
        # The zip's absence is already reported. Comparing the symlink against a zip
        # timestamp of 0.0 would call every symlink fresh, which is the same bug in
        # miniature.
        symlink = tmp_path / "series" / "comic.cbz"
        symlink.parent.mkdir(parents=True, exist_ok=True)
        symlink.symlink_to(tmp_path / "comic.cbz")

        errors = check_zip_symlink_freshness(
            symlink, ZipOutOfDateErrors(file=tmp_path / "comic.cbz", missing=True), None
        )

        assert not errors.out_of_date_wrt_zip


class FakeComic:
    """The three dest artifacts `check_zip_files` grades.

    Stands in for a `ComicBook`: only the three accessors that check calls are
    implemented, so no comics database or ini file is needed.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.zip_file = tmp_path / "dest" / "comic.cbz"
        self.series_symlink = tmp_path / "series" / "comic.cbz"
        self.year_symlink = tmp_path / "year" / "comic.cbz"

    def get_dest_comic_zip(self) -> Path:
        return self.zip_file

    def get_dest_series_comic_zip_symlink(self) -> Path:
        return self.series_symlink

    def get_dest_year_comic_zip_symlink(self) -> Path:
        return self.year_symlink


def as_comic(fake: FakeComic) -> ComicBook:
    """Present a `FakeComic` as the `ComicBook` the check is typed against."""
    return cast("ComicBook", fake)


def make_errors() -> OutOfDateErrors:
    """Make an empty findings record for one title."""
    return ComicsIntegrityChecker.make_out_of_date_errors("Fake Title")


@pytest.fixture
def comic(tmp_path: Path) -> FakeComic:
    return FakeComic(tmp_path)


class TestBothSymlinksAreGraded:
    """One run has to report everything wrong, not just the first thing.

    `check_zip_files` used to `return` at the first missing symlink, so a title missing
    both was reported as missing one, and recreating it revealed the second only on the
    next run.
    """

    @staticmethod
    def _check(comic: FakeComic) -> OutOfDateErrors:
        """Grade a comic's zip and both symlinks."""
        errors = make_errors()
        checker = ComicsIntegrityChecker(
            cast("ComicsDatabase", object()),
            no_check_for_unexpected_files=False,
            no_check_symlinks=False,
        )
        checker.check_zip_files(as_comic(comic), errors)

        return errors

    def test_a_missing_series_symlink_does_not_hide_a_missing_year_symlink(
        self, comic: FakeComic
    ) -> None:
        touch_at(comic.zip_file, NEW)

        errors = self._check(comic)

        assert errors.series_zip_symlink_errors.missing
        assert errors.year_zip_symlink_errors.missing

    def test_a_missing_series_symlink_does_not_hide_a_stale_year_symlink(
        self, comic: FakeComic
    ) -> None:
        touch_at(comic.zip_file, NEW)
        comic.year_symlink.parent.mkdir(parents=True, exist_ok=True)
        comic.year_symlink.symlink_to(comic.zip_file)
        os.utime(comic.year_symlink, (OLD, OLD), follow_symlinks=False)

        errors = self._check(comic)

        assert errors.series_zip_symlink_errors.missing
        assert errors.year_zip_symlink_errors.out_of_date_wrt_zip

    def test_a_missing_zip_still_reports_both_symlinks(self, comic: FakeComic) -> None:
        errors = self._check(comic)

        assert errors.zip_errors.missing
        assert errors.series_zip_symlink_errors.missing
        assert errors.year_zip_symlink_errors.missing


class TestOutOfDateMessage:
    def test_a_missing_input_is_named_rather_than_compared(self, tmp_path: Path) -> None:
        # How a missing-stage dependency reads. There is no timestamp to compare, so
        # naming the absent file is the whole message - which is why these branches are
        # not dead defensiveness.
        dest = touch_at(tmp_path / "dest.jpg", NEW)
        gone = tmp_path / "restored.png"

        msg = get_file_out_of_date_with_other_file_msg(dest, gone, ERROR_PREFIX)

        assert msg == f'{ERROR_PREFIX}File "{gone}" is missing.'

    def test_a_missing_input_message_still_carries_the_error_prefix(self, tmp_path: Path) -> None:
        # The out-of-date half being the absent one is a guard rather than an ordinary-run
        # path - the walk no longer pairs a present stage against a missing one - but the
        # comparison it stands in front of stats both files and would raise. It carries the
        # prefix like every other finding: an unprefixed line would flip the exit code while
        # slipping past any filter that greps the report for the prefix.
        dest = tmp_path / "dest.jpg"
        srce = touch_at(tmp_path / "restored.png", NEW)

        msg = get_file_out_of_date_with_other_file_msg(dest, srce, ERROR_PREFIX)

        assert msg.startswith(ERROR_PREFIX)

    def test_a_real_inversion_names_both_files_and_both_times(self, tmp_path: Path) -> None:
        dest = touch_at(tmp_path / "dest.jpg", OLD)
        srce = touch_at(tmp_path / "restored.png", NEW)

        msg = get_file_out_of_date_with_other_file_msg(dest, srce, ERROR_PREFIX)

        assert "is out of date with" in msg
        assert "dest.jpg" in msg
        assert "restored.png" in msg
