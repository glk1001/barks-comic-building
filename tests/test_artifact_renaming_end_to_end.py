"""The artifact rename fix, run whole against a library laid out on disk.

The other two rename test files build `RenamePlan` objects by hand and check the pieces.
Nothing ran the scan, the matching across all four namespaces and the apply together, so
the joins between them - the keys two functions must agree on, the wider symlink scan,
the order the stages run in - were covered by nothing. This lays out a small library that
has been renumbered and runs the fix over it, twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from barks_comic_building.build import artifact_renaming
from barks_comic_building.build.artifact_renaming import (
    ArtifactKind,
    Disposition,
    build_expected_artifacts,
    build_rename_plan,
    run_artifact_rename_fix,
    scan_actual_artifacts,
)
from barks_comic_building.build.zipping import relative_symlink

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comics_database import ComicsDatabase


class FakeComic:
    """The dest paths the fix reads from a `ComicBook`, for one title at one number."""

    def __init__(self, library: Library, title: str, number: int, series_number: int) -> None:
        self._library = library
        self._name = f"{number:03d} {title}"
        self._zip_name = f"{number:03d} {title} [WDCS {number}].cbz"
        self._series_name = f"{series_number:03d} {title} [WDCS {number}].cbz"

    def get_dest_rel_dirname(self) -> str:
        return self._name

    def get_dest_dir(self) -> Path:
        return self._library.dirs_root / self._name

    def get_dest_comic_zip(self) -> Path:
        return self._library.zips_root / self._zip_name

    def get_dest_series_comic_zip_symlink(self) -> Path:
        return self._library.series_dir / self._series_name

    def get_dest_year_comic_zip_symlink(self) -> Path:
        return self._library.year_dir / self._zip_name


class Library:
    """A comics tree under `tmp_path`, and the database that says what it should hold."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = tmp_path / "The Comics"
        self.dirs_root = self.root / "aaa-Chronological-dirs"
        self.zips_root = self.root / "Chronological"
        self.years_root = self.root / "Chronological Years"
        self.series_dir = self.root / "Donald Duck"
        self.year_dir = self.years_root / "1949"
        for path in (self.dirs_root, self.zips_root, self.series_dir, self.year_dir):
            path.mkdir(parents=True)

        monkeypatch.setattr(artifact_renaming, "THE_COMICS_DIR", self.root)
        monkeypatch.setattr(artifact_renaming, "THE_CHRONOLOGICAL_DIRS_DIR", self.dirs_root)
        monkeypatch.setattr(artifact_renaming, "THE_CHRONOLOGICAL_DIR", self.zips_root)
        monkeypatch.setattr(artifact_renaming, "THE_YEARS_COMICS_DIR", self.years_root)

        self.comics: dict[str, FakeComic] = {}
        self.will_not_load: set[str] = set()

    def configure(self, title: str, number: int, series_number: int) -> FakeComic:
        """Say where `title`'s artifacts should be now."""
        self.comics[title] = FakeComic(self, title, number, series_number)

        return self.comics[title]

    def build(self, comic: FakeComic) -> None:
        """Put a built comic on disk at the names `comic` gives."""
        comic.get_dest_dir().mkdir()
        comic.get_dest_comic_zip().write_text("a built comic")
        relative_symlink(comic.get_dest_comic_zip(), comic.get_dest_series_comic_zip_symlink())
        relative_symlink(comic.get_dest_comic_zip(), comic.get_dest_year_comic_zip_symlink())

    def names(self, directory: Path) -> list[str]:
        return sorted(path.name for path in directory.iterdir())

    # The two calls the fix makes on a `ComicsDatabase`.
    def get_all_story_titles(self) -> list[str]:
        return [*self.comics, *sorted(self.will_not_load)]

    def get_comic_book(self, title: str) -> FakeComic:
        if title in self.will_not_load:
            msg = "could not parse the ini"
            raise ValueError(msg)

        return self.comics[title]


def as_database(library: Library) -> ComicsDatabase:
    return cast("ComicsDatabase", library)


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Library:
    return Library(tmp_path, monkeypatch)


@pytest.fixture
def renumbered(library: Library) -> Library:
    """Two titles built at 001 and 002, then a title inserted ahead of both.

    Each shifts up one chronologically; "Second" also moves up one in its series, which
    is a separate count.
    """
    library.build(FakeComic(library, "First", 1, 1))
    library.build(FakeComic(library, "Second", 2, 2))
    library.configure("First", 2, 1)
    library.configure("Second", 3, 3)

    return library


class TestARenumberedLibrary:
    def test_a_dry_run_reports_the_work_and_changes_nothing(self, renumbered: Library) -> None:
        before = renumbered.names(renumbered.zips_root)

        assert run_artifact_rename_fix(as_database(renumbered), apply=False) == 1
        assert renumbered.names(renumbered.zips_root) == before

    def test_applying_moves_every_artifact_onto_its_new_number(self, renumbered: Library) -> None:
        assert run_artifact_rename_fix(as_database(renumbered), apply=True) == 0

        assert renumbered.names(renumbered.dirs_root) == ["002 First", "003 Second"]
        assert renumbered.names(renumbered.zips_root) == [
            "002 First [WDCS 2].cbz",
            "003 Second [WDCS 3].cbz",
        ]
        assert renumbered.names(renumbered.series_dir) == [
            "001 First [WDCS 2].cbz",
            "003 Second [WDCS 3].cbz",
        ]
        assert renumbered.names(renumbered.year_dir) == [
            "002 First [WDCS 2].cbz",
            "003 Second [WDCS 3].cbz",
        ]

    def test_every_link_resolves_to_its_renamed_zip(self, renumbered: Library) -> None:
        run_artifact_rename_fix(as_database(renumbered), apply=True)

        for comic in renumbered.comics.values():
            zip_file = comic.get_dest_comic_zip()
            assert zip_file.read_text() == "a built comic"
            assert comic.get_dest_series_comic_zip_symlink().resolve() == zip_file.resolve()
            assert comic.get_dest_year_comic_zip_symlink().resolve() == zip_file.resolve()

    def test_a_second_run_finds_nothing_to_do(self, renumbered: Library) -> None:
        run_artifact_rename_fix(as_database(renumbered), apply=True)

        plan = build_rename_plan(as_database(renumbered))

        assert plan.dest_dir_steps == []
        assert plan.zip_steps == []
        assert plan.symlink_fixes == []
        assert {fix.disposition for fix in plan.fixes} == {Disposition.OK}
        assert run_artifact_rename_fix(as_database(renumbered), apply=False) == 0


class TestWhatTheScanFinds:
    def test_a_link_left_in_another_series_directory_is_found_and_dropped(
        self, renumbered: Library
    ) -> None:
        # A title that changed series leaves its old link in a directory the expected
        # paths never mention - which is why every series directory is scanned.
        other_series = renumbered.root / "Uncle Scrooge"
        other_series.mkdir()
        stale = other_series / "009 First [WDCS 1].cbz"
        relative_symlink(renumbered.zips_root / "001 First [WDCS 1].cbz", stale)

        assert stale in scan_actual_artifacts().series_symlinks["First"]

        run_artifact_rename_fix(as_database(renumbered), apply=True)

        assert not stale.is_symlink()

    def test_an_artifact_of_no_configured_title_is_an_orphan_and_is_left(
        self, renumbered: Library
    ) -> None:
        stray = renumbered.dirs_root / "099 Unconfigured"
        stray.mkdir()

        plan = build_rename_plan(as_database(renumbered))
        run_artifact_rename_fix(as_database(renumbered), apply=True)

        assert (ArtifactKind.DEST_DIR, Disposition.ORPHAN, stray) in [
            (fix.kind, fix.disposition, fix.current) for fix in plan.fixes
        ]
        assert stray.is_dir()

    def test_a_name_with_no_number_is_reported_as_unparsable(self, renumbered: Library) -> None:
        odd = renumbered.zips_root / "notes.txt"
        odd.touch()

        assert (ArtifactKind.ZIP, odd) in build_rename_plan(as_database(renumbered)).unparsable

    def test_a_configured_title_with_nothing_on_disk_is_unbuilt(self, renumbered: Library) -> None:
        renumbered.configure("Third", 4, 4)

        assert build_rename_plan(as_database(renumbered)).unbuilt_titles == ["Third"]


class TestTheExpectedArtifacts:
    def test_a_title_that_will_not_load_is_a_load_error_and_fails_the_fix(
        self, renumbered: Library
    ) -> None:
        renumbered.will_not_load.add("Broken")

        expected, load_errors = build_expected_artifacts(as_database(renumbered))

        assert sorted(expected) == ["First", "Second"]
        assert len(load_errors) == 1
        assert run_artifact_rename_fix(as_database(renumbered), apply=True) == 1
        # The titles that did load were still fixed.
        assert renumbered.names(renumbered.dirs_root) == ["002 First", "003 Second"]

    def test_a_title_whose_zip_name_carries_another_key_is_refused(self, library: Library) -> None:
        # The premise that lets renames go unordered: every name parses back to its own
        # title. A title that broke it could be matched to another title's artifacts.
        comic = library.configure("First", 1, 1)
        comic._zip_name = "001 Something Else [WDCS 1].cbz"  # noqa: SLF001

        expected, load_errors = build_expected_artifacts(as_database(library))

        assert expected == {}
        assert len(load_errors) == 1
        assert "First" in load_errors[0]
