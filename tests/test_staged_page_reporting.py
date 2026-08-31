"""Tests for a finding against a page that lives in another volume.

The synthetic collections are assembled from symlinks into the volumes their members
belong to, so a finding against `All One-Pagers` page 593 names a path in the collection
when the file to fix is page 095 of volume 20. That is not a cosmetic problem, for two
reasons.

The collection is the *only* place these pages are checked. The per-volume walk goes
title by title, and a one-pager has no `.ini` of its own, so volume 20's own run never
reaches page 095 - it is not that the report says it twice and once unhelpfully, it is
that this is the only time it will ever be said.

And the advice it used to print was wrong for exactly these pages. An override put in
the collection's `bounded/` directory is keyed by the collection page number, so it is
not the one the page is bounded against, and `barks-batch-panel-bounds` skips a linked
page in any case - the run would report success and change nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from barks_fantagraphics.comics_utils import get_relpath

from barks_comic_building.build.comics_integrity import (
    ComicsIntegrityChecker,
    staged_page_source,
)

TITLE = "All One-Pagers"


class StagedPage:
    """One collection page's segments json and the restored scan it was computed from.

    Mirrors the real trees closely enough for the one thing under test: both live under a
    `Fantagraphics-*` directory named for the volume, and either may be a link into the
    volume the page really belongs to.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "Carl Barks"
        self.collection = "Carl Barks Vol. 1 - Donald Duck - Finds Pirate Gold"
        self.home = "Carl Barks Vol. 20 - Uncle Scrooge - The Mines of King Solomon"

        self.segments = self._make(
            "Fantagraphics-restored-panel-segments", self.collection, "593.json"
        )
        self.scan = self._make("Fantagraphics-restored", self.collection, "images/593.png")
        self.home_segments = self._make(
            "Fantagraphics-restored-panel-segments", self.home, "095.json"
        )
        self.home_scan = self._make("Fantagraphics-restored", self.home, "images/095.png")
        for path in (self.home_segments, self.home_scan):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def _make(self, tree: str, volume: str, name: str) -> Path:
        return self.root / tree / volume / name

    def stage(self, path: Path, target: Path) -> None:
        """Link one collection slot at the page's real file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)

    def write_locally(self, path: Path) -> None:
        """Write a real file into the collection, as the pipeline run on it does."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    def source(self) -> Path | None:
        return staged_page_source(self.segments, self.scan)


@pytest.fixture
def page(tmp_path: Path) -> StagedPage:
    return StagedPage(tmp_path)


class TestWhereTheWorkIs:
    def test_a_page_of_this_volume_needs_no_redirect(self, page: StagedPage) -> None:
        page.write_locally(page.segments)
        page.write_locally(page.scan)

        assert page.source() is None

    def test_an_ordinary_staged_page_points_at_its_own_volume(self, page: StagedPage) -> None:
        page.stage(page.segments, page.home_segments)
        page.stage(page.scan, page.home_scan)

        assert page.source() == page.home_scan

    def test_segments_written_into_the_collection_still_point_home(self, page: StagedPage) -> None:
        # `The Big Bobber`: its home volume had not been bounded, so there was nothing to
        # link and the segments were written here as a real file - computed against this
        # collection's `bounded/` directory, keyed by the collection page number, so the
        # home volume's override was never seen. The scan above them is still a link, and
        # is the only thing left that says so.
        page.write_locally(page.segments)
        page.stage(page.scan, page.home_scan)

        assert page.source() == page.home_scan

    def test_a_linked_segments_file_alone_is_enough(self, page: StagedPage) -> None:
        page.stage(page.segments, page.home_segments)
        page.write_locally(page.scan)

        assert page.source() == page.home_segments

    def test_a_relative_link_is_made_absolute(self, page: StagedPage) -> None:
        page.write_locally(page.segments)
        page.scan.parent.mkdir(parents=True, exist_ok=True)
        page.scan.symlink_to(Path("..") / ".." / page.home / "images" / "095.png")

        source = page.source()

        assert source is not None
        assert source.is_absolute()
        assert source.resolve() == page.home_scan.resolve()


class TestOnlyTheLinkIsFollowed:
    """`Path.resolve` would follow the library directory too, and that loses the volume."""

    def test_a_library_dir_that_is_itself_a_symlink_keeps_its_name(self, tmp_path: Path) -> None:
        # The real `Fantagraphics-*` directories are symlinks onto another drive. Resolved
        # in full, a page lands outside `BARKS_ROOT_DIR`, where `get_relpath` prints only
        # the last two components - cutting the volume, which is the whole point of naming
        # the path at all, and leaving "images/095.png".
        elsewhere = tmp_path / "other-drive" / "Fantagraphics-restored"
        home_scan = elsewhere / "Carl Barks Vol. 20 - The Mines of King Solomon" / "095.png"
        home_scan.parent.mkdir(parents=True, exist_ok=True)
        home_scan.touch()

        library = tmp_path / "Carl Barks" / "Fantagraphics-restored"
        library.parent.mkdir(parents=True, exist_ok=True)
        library.symlink_to(elsewhere)

        collection = library / "Carl Barks Vol. 1 - Finds Pirate Gold"
        collection.mkdir(parents=True, exist_ok=True)
        scan = collection / "593.png"
        scan.symlink_to(home_scan)

        source = staged_page_source(collection / "593.json", scan)

        assert source is not None
        assert source == home_scan
        assert "Carl Barks Vol. 20 - The Mines of King Solomon" in source.parts


class TestWhatTheReportSays:
    @staticmethod
    def _report(page: StagedPage) -> None:
        errors = ComicsIntegrityChecker.make_out_of_date_errors(TITLE)
        errors.invalid_panel_segments.append(
            (
                page.segments,
                ("Panels 2 and 3 overlap by 48.9% of the smaller panel.",),
                page.source(),
            )
        )
        ComicsIntegrityChecker.print_out_of_date_or_missing_errors(errors)

    def test_a_staged_page_is_sent_to_its_own_volume(
        self, page: StagedPage, capsys: pytest.CaptureFixture[str]
    ) -> None:
        page.stage(page.segments, page.home_segments)
        page.stage(page.scan, page.home_scan)

        self._report(page)
        out = capsys.readouterr().out

        assert "staged from another volume" in out
        assert get_relpath(page.home_scan) in out
        # The local advice would send the fix to a `bounded/` directory keyed by the
        # collection page number, where nothing would ever read it.
        assert "NNN-panel-order.json" not in out

    def test_a_page_of_this_volume_keeps_the_override_advice(
        self, page: StagedPage, capsys: pytest.CaptureFixture[str]
    ) -> None:
        page.write_locally(page.segments)
        page.write_locally(page.scan)

        self._report(page)
        out = capsys.readouterr().out

        assert "staged from another volume" not in out
        assert "NNN-panel-order.json" in out

    def test_the_finding_still_fails_the_run(self, page: StagedPage) -> None:
        page.stage(page.segments, page.home_segments)
        page.stage(page.scan, page.home_scan)
        errors = ComicsIntegrityChecker.make_out_of_date_errors(TITLE)
        errors.invalid_panel_segments.append((page.segments, ("overlap",), page.source()))

        assert errors.is_error
