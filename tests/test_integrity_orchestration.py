"""Tests for the integrity checker's own methods - the layer between the rules and a run.

The rules a finding is decided by are pure functions with tests of their own. What was
not tested is the checker that gathers the facts for them and decides what runs when:
most of its methods were referenced by no test at all, and the faults found in review -
a directory reported twice, a fault that hid another - were all in this layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from barks_build_comic_images.consts import DEST_NON_IMAGE_FILES
from barks_fantagraphics.barks_titles import Titles
from barks_fantagraphics.comics_consts import IMAGES_SUBDIR
from barks_fantagraphics.fanta_comics_info import SERIES_MISC

from barks_comic_building.build import comics_integrity
from barks_comic_building.build.comics_integrity import (
    STANDARD_FIXES,
    UPSCAYLED_FIXES,
    ComicsIntegrityChecker,
    HashErrors,
)
from barks_comic_building.build.utils import (
    MaxTimestamp,
    ZipOutOfDateErrors,
    ZipSymlinkOutOfDateErrors,
)

if TYPE_CHECKING:
    from barks_fantagraphics.comic_book import ComicBook
    from barks_fantagraphics.comics_database import ComicsDatabase

VOLUME = 7
NUM_VOLUME_PAGES = 240
NEWER = 2_000_000_000.0


class FakeDatabase:
    """The directories and titles the checker asks a `ComicsDatabase` for."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.volume_of: dict[str, int] = {}
        self.titles_loaded = 0

    def _images(self, tree: str, volume: int) -> Path:
        return self._root / tree / f"volume-{volume:02d}" / IMAGES_SUBDIR

    def get_fantagraphics_volume_image_dir(self, volume: int) -> Path:
        return self._images("original", volume)

    def get_fantagraphics_fixes_volume_dir(self, volume: int) -> Path:
        return self._images("fixes", volume).parent

    def get_fantagraphics_fixes_volume_image_dir(self, volume: int) -> Path:
        return self._images("fixes", volume)

    def get_fantagraphics_upscayled_fixes_volume_dir(self, volume: int) -> Path:
        return self._images("upscayled-fixes", volume).parent

    def get_fantagraphics_upscayled_fixes_volume_image_dir(self, volume: int) -> Path:
        return self._images("upscayled-fixes", volume)

    def get_num_pages_in_fantagraphics_volume(self, _volume: int) -> int:
        return NUM_VOLUME_PAGES

    def get_configured_titles_in_fantagraphics_volumes(
        self, _volumes: list[int]
    ) -> list[tuple[str, object]]:
        self.titles_loaded += 1
        return []

    def get_all_story_titles(self) -> list[str]:
        return list(self.volume_of)

    def get_fanta_volume_int(self, title: str) -> int:
        return self.volume_of[title]


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()

    return path


def make_checker(database: object) -> ComicsIntegrityChecker:
    return ComicsIntegrityChecker(
        cast("ComicsDatabase", database),
        no_check_for_unexpected_files=False,
        no_check_symlinks=False,
    )


@pytest.fixture
def database(tmp_path: Path) -> FakeDatabase:
    return FakeDatabase(tmp_path)


class TestTheFixesTree:
    @staticmethod
    def _fix(database: FakeDatabase, name: str) -> Path:
        """Put a fix for a page that has an original scan into the standard tree."""
        touch(database.get_fantagraphics_volume_image_dir(VOLUME) / (Path(name).stem + ".jpg"))

        return touch(database.get_fantagraphics_fixes_volume_image_dir(VOLUME) / name)

    def test_a_fix_for_a_page_with_an_original_passes(self, database: FakeDatabase) -> None:
        self._fix(database, "005.jpg")

        assert make_checker(database).check_fixes_tree(VOLUME, STANDARD_FIXES) == 0

    def test_a_page_fixed_in_both_extensions_is_reported(
        self, database: FakeDatabase, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._fix(database, "005.jpg")
        self._fix(database, "005.png")

        assert make_checker(database).check_fixes_tree(VOLUME, STANDARD_FIXES) == 1
        assert "has both a .jpg and a .png" in capsys.readouterr().out

    def test_a_tree_with_no_images_dir_fails_before_its_files_are_read(
        self, database: FakeDatabase, capsys: pytest.CaptureFixture[str]
    ) -> None:
        touch(database.get_fantagraphics_fixes_volume_dir(VOLUME) / "stray.txt")

        assert make_checker(database).check_fixes_tree(VOLUME, STANDARD_FIXES) == 1
        assert "Could not find" in capsys.readouterr().out

    def test_a_volume_root_holding_more_than_its_images_dir_fails(
        self, database: FakeDatabase, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._fix(database, "005.jpg")
        touch(database.get_fantagraphics_fixes_volume_dir(VOLUME) / "stray.txt")

        assert make_checker(database).check_fixes_tree(VOLUME, STANDARD_FIXES) == 1
        assert "too many files" in capsys.readouterr().out

    def test_the_standard_pass_reads_the_volumes_titles(self, database: FakeDatabase) -> None:
        self._fix(database, "005.jpg")

        make_checker(database).check_fixes_tree(VOLUME, STANDARD_FIXES)

        assert database.titles_loaded == 1

    def test_the_upscayled_pass_loads_no_titles(self, database: FakeDatabase) -> None:
        # It has no added-pages band, so the policy built from every ini in the volume
        # was read by nothing.
        touch(database.get_fantagraphics_volume_image_dir(VOLUME) / "005.jpg")
        touch(database.get_fantagraphics_upscayled_fixes_volume_image_dir(VOLUME) / "005.png")

        assert make_checker(database).check_fixes_tree(VOLUME, UPSCAYLED_FIXES) == 0
        assert database.titles_loaded == 0


class FakeFantaInfo:
    def __init__(self, series_name: str) -> None:
        self.series_name = series_name


class FakeComic:
    def __init__(
        self,
        tmp_path: Path,
        *,
        extra_pub_info: str = "",
        series_name: str = "Donald Duck",
        title_enum: Titles = Titles.BIRD_WATCHING,
    ) -> None:
        self.dest_dir = tmp_path / "dest"
        self.chronological_number = 42
        self.extra_pub_info = extra_pub_info
        self.fanta_info = FakeFantaInfo(series_name)
        self._title_enum = title_enum

    def get_dest_dir(self) -> Path:
        return self.dest_dir

    def get_title_enum(self) -> Titles:
        return self._title_enum


def as_comic(comic: FakeComic) -> ComicBook:
    return cast("ComicBook", comic)


class TestTheStoryAttributes:
    def test_a_barks_script_passes(self, tmp_path: Path) -> None:
        comic = FakeComic(tmp_path)

        assert ComicsIntegrityChecker.check_story_attributes(as_comic(comic), "A Title") == 0

    def test_a_script_by_someone_else_must_be_in_misc(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        comic = FakeComic(tmp_path, extra_pub_info="Script: Someone Else")

        assert ComicsIntegrityChecker.check_story_attributes(as_comic(comic), "A Title") == 1
        assert "should be in MISC" in capsys.readouterr().out

    def test_one_that_is_in_misc_passes(self, tmp_path: Path) -> None:
        comic = FakeComic(tmp_path, extra_pub_info="Script: Someone Else", series_name=SERIES_MISC)

        assert ComicsIntegrityChecker.check_story_attributes(as_comic(comic), "A Title") == 0


class TestTheComicStructure:
    def test_a_comic_of_one_page_is_too_small(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(comics_integrity, "get_total_num_pages", lambda _comic: 1)
        checker = make_checker(object())

        assert checker.check_comic_structure(as_comic(FakeComic(tmp_path)), "A Title") == 1
        assert "page count is too small" in capsys.readouterr().out

    def test_a_hash_fault_fails_the_structure_and_is_printed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def unbuilt(_comic: object, errors: HashErrors) -> int:
            errors.metadata_file = tmp_path / "comic-metadata.json"
            return 1

        monkeypatch.setattr(comics_integrity, "get_total_num_pages", lambda _comic: 12)
        checker = make_checker(object())
        monkeypatch.setattr(checker, "check_hashes", unbuilt)

        assert checker.check_comic_structure(as_comic(FakeComic(tmp_path)), "A Title") == 1
        assert "has not been built" in capsys.readouterr().out

    def test_a_built_comic_of_many_pages_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(comics_integrity, "get_total_num_pages", lambda _comic: 12)
        checker = make_checker(object())
        monkeypatch.setattr(checker, "check_hashes", lambda _comic, _errors: 0)

        assert checker.check_comic_structure(as_comic(FakeComic(tmp_path)), "A Title") == 0


class TestTheInfoFiles:
    @staticmethod
    def _built(comic: FakeComic) -> None:
        for name in DEST_NON_IMAGE_FILES:
            touch(comic.dest_dir / name)

    def test_a_dest_dir_that_is_not_there_is_the_one_finding(self, tmp_path: Path) -> None:
        comic = FakeComic(tmp_path)
        errors = ComicsIntegrityChecker.make_out_of_date_errors("A Title")

        ComicsIntegrityChecker.check_additional_files(as_comic(comic), errors)

        assert errors.dest_dir_files_missing == [comic.dest_dir]

    def test_a_complete_dest_dir_has_no_findings(self, tmp_path: Path) -> None:
        comic = FakeComic(tmp_path)
        self._built(comic)
        errors = ComicsIntegrityChecker.make_out_of_date_errors("A Title")

        ComicsIntegrityChecker.check_additional_files(as_comic(comic), errors)

        assert not errors.is_error

    def test_each_missing_info_file_is_named_in_a_fixed_order(self, tmp_path: Path) -> None:
        comic = FakeComic(tmp_path)
        comic.dest_dir.mkdir()
        errors = ComicsIntegrityChecker.make_out_of_date_errors("A Title")

        ComicsIntegrityChecker.check_additional_files(as_comic(comic), errors)

        assert errors.dest_dir_files_missing == [
            comic.dest_dir / name for name in sorted(DEST_NON_IMAGE_FILES)
        ]

    def test_info_files_older_than_the_newest_source_are_out_of_date(self, tmp_path: Path) -> None:
        comic = FakeComic(tmp_path)
        self._built(comic)
        errors = ComicsIntegrityChecker.make_out_of_date_errors("A Title")
        errors.max_srce = MaxTimestamp(tmp_path / "newer.png", NEWER)

        ComicsIntegrityChecker.check_additional_files(as_comic(comic), errors)

        assert len(errors.dest_dir_files_out_of_date) == len(DEST_NON_IMAGE_FILES)
        assert errors.is_error


class TestTheReport:
    def test_a_missing_zip_and_its_links_are_each_named(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        errors = ComicsIntegrityChecker.make_out_of_date_errors("A Title")
        errors.zip_errors = ZipOutOfDateErrors(file=tmp_path / "a.cbz", missing=True)
        errors.series_zip_symlink_errors = ZipSymlinkOutOfDateErrors(
            symlink=tmp_path / "series.cbz", missing=True
        )
        errors.year_zip_symlink_errors = ZipSymlinkOutOfDateErrors(
            symlink=tmp_path / "year.cbz", missing=True
        )

        make_checker(object()).print_check_errors(errors)

        out = capsys.readouterr().out
        assert f'the zip file "{tmp_path / "a.cbz"}" is missing' in out
        assert "the series symlink" in out
        assert "the year symlink" in out

    def test_a_clean_title_prints_nothing(self, capsys: pytest.CaptureFixture[str]) -> None:
        errors = ComicsIntegrityChecker.make_out_of_date_errors("A Title")

        make_checker(object()).print_check_errors(errors)

        assert capsys.readouterr().out == ""


class TestTheRun:
    @staticmethod
    def _checker(
        database: FakeDatabase,
        monkeypatch: pytest.MonkeyPatch,
        *,
        preconditions: int = 0,
        failing_titles: tuple[str, ...] = (),
        unexpected_files: int = 0,
    ) -> tuple[ComicsIntegrityChecker, list[str]]:
        """Return a checker whose gates and per-title check answer as told."""
        database.volume_of = {"A": 1, "B": 1, "C": 2}
        checker = make_checker(database)
        checked: list[str] = []

        def check_single_title(title: str) -> int:
            checked.append(title)
            return 1 if title in failing_titles else 0

        monkeypatch.setattr(checker, "_check_preconditions", lambda _titles: preconditions)
        monkeypatch.setattr(checker, "check_no_unexpected_files", lambda: unexpected_files)
        monkeypatch.setattr(checker, "check_single_title", check_single_title)

        return checker, checked

    def test_a_clean_library_passes_and_every_title_is_checked(
        self, database: FakeDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checker, checked = self._checker(database, monkeypatch)

        assert checker.check_comics_integrity([]) == 0
        assert checked == ["A", "B", "C"]

    def test_a_failed_precondition_stops_the_run_before_any_title(
        self, database: FakeDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checker, checked = self._checker(database, monkeypatch, preconditions=1)

        assert checker.check_comics_integrity([]) == 1
        assert checked == []

    def test_one_failing_title_fails_the_run_and_the_rest_are_still_checked(
        self, database: FakeDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checker, checked = self._checker(database, monkeypatch, failing_titles=("A",))

        assert checker.check_comics_integrity([]) == 1
        assert checked == ["A", "B", "C"]

    def test_unexpected_files_alone_fail_the_run(
        self, database: FakeDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checker, _checked = self._checker(database, monkeypatch, unexpected_files=1)

        assert checker.check_comics_integrity([]) == 1

    def test_a_title_list_narrows_the_run(
        self, database: FakeDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checker, checked = self._checker(database, monkeypatch)

        assert checker.check_comics_integrity(["C"]) == 0
        assert checked == ["C"]

    def test_a_title_that_would_not_load_fails_a_run_that_never_reached_it(
        self, database: FakeDatabase, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Met by a whole-library check while the run itself was narrowed to other titles.
        checker, _checked = self._checker(database, monkeypatch)
        checker._failed_load_titles.add("B")  # noqa: SLF001

        assert checker.check_comics_integrity(["C"]) == 1
