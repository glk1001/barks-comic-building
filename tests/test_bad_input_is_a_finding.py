"""Tests that one damaged input costs one title its result, not the whole run its.

The build, the integrity check, the rename fix and the censorship CSV tool all work
through many titles. Each used to let one title's bad data - an ini that will not parse,
a truncated metadata file, a page fixed in both extensions, a typo in a story name -
raise straight out of the loop, so every title after it went unbuilt or unchecked and
the fault itself arrived as a traceback. The integrity check is the tool meant to report
a damaged file; being stopped by one is the failure these pin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from barks_comic_building.build import batch_build_comics, censorship_csv, comics_integrity
from barks_comic_building.build.artifact_renaming import build_expected_artifacts
from barks_comic_building.build.censorship_csv import CensorshipCsvError, locate_stories
from barks_comic_building.build.collection_sources import FixesPairError
from barks_comic_building.build.comics_integrity import (
    STANDARD_FIXES,
    UPSCAYLED_FIXES,
    ComicsIntegrityChecker,
    HashErrors,
    check_panel_segments_file,
    is_second_of_fixes_pair,
)
from barks_comic_building.build.utils import error_summary

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from barks_fantagraphics.censorship_fixes import CensorshipFixRow
    from barks_fantagraphics.comic_book import ComicBook
    from barks_fantagraphics.comics_database import ComicsDatabase

BAD_TITLE = "A Bad Title"
GOOD_TITLE = "A Good Title"


class FakeComic:
    """As much of a `ComicBook` as the hash check and the title check read."""

    def __init__(self, tmp_path: Path) -> None:
        self.ini_file = tmp_path / "title.ini"
        self.ini_file.write_text("[info]\n")
        self._metadata_file = tmp_path / "metadata.json"

    def get_metadata_filepath(self) -> Path:
        return self._metadata_file

    def get_comic_title(self) -> str:
        # Not a load fault, and not anything a check expects: the backstop's case.
        msg = "a bug in a check"
        raise ZeroDivisionError(msg)


class FakeDatabase:
    """A database of two titles, one of which will not load."""

    def __init__(self, good_comic: object = None, titles: list[str] | None = None) -> None:
        self._good_comic = good_comic
        self._titles = titles or [BAD_TITLE, GOOD_TITLE]

    def get_all_story_titles(self) -> list[str]:
        return self._titles

    def get_comic_book(self, title: str) -> object:
        if title == BAD_TITLE:
            msg = "invalid literal for int() with base 10: 'x'"
            raise ValueError(msg)

        return self._good_comic


def make_checker(database: FakeDatabase) -> ComicsIntegrityChecker:
    return ComicsIntegrityChecker(
        cast("ComicsDatabase", database),
        no_check_for_unexpected_files=False,
        no_check_symlinks=False,
    )


class TestErrorSummary:
    def test_an_exception_with_no_message_is_still_named(self) -> None:
        assert error_summary(AssertionError()) == "AssertionError"

    def test_the_type_goes_with_the_message(self) -> None:
        assert error_summary(KeyError("pages")) == "KeyError: 'pages'"


class TestTheIntegrityCheckSurvivesATitleThatWillNotLoad:
    def test_the_title_fails_and_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        checker = make_checker(FakeDatabase())

        assert checker.check_single_title(BAD_TITLE) == 1
        out = capsys.readouterr().out
        assert f'Could not load "{BAD_TITLE}"' in out
        assert "ValueError" in out

    def test_it_is_reported_once_however_many_checks_load_it(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        checker = make_checker(FakeDatabase())

        # More than one check walks every title, so the same ini is met several times.
        assert checker._load_comic(BAD_TITLE) is None  # noqa: SLF001
        assert checker._load_comic(BAD_TITLE) is None  # noqa: SLF001

        assert capsys.readouterr().out.count("Could not load") == 1

    def test_a_check_that_blows_up_costs_only_its_own_title(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        checker = make_checker(FakeDatabase(FakeComic(tmp_path)))

        assert checker.check_single_title(GOOD_TITLE) == 1
        assert f'The check of "{GOOD_TITLE}" did not finish' in capsys.readouterr().out


class TestDamagedFilesAreFindings:
    def test_a_truncated_metadata_file_is_reported_not_raised(self, tmp_path: Path) -> None:
        comic = FakeComic(tmp_path)
        comic.get_metadata_filepath().write_text('{"title": "A Fake Ti')
        errors = HashErrors()

        assert ComicsIntegrityChecker.check_hashes(cast("ComicBook", comic), errors) == 1
        assert errors.metadata_unreadable is not None
        assert errors.metadata_unreadable[0] == comic.get_metadata_filepath()

    def test_metadata_that_is_not_text_is_reported_not_raised(self, tmp_path: Path) -> None:
        # What a flipped bit makes of a json file: bytes that are not utf-8 at all.
        comic = FakeComic(tmp_path)
        comic.get_metadata_filepath().write_bytes(b'{"ini_hash": "\xff\xfe"}')
        errors = HashErrors()

        assert ComicsIntegrityChecker.check_hashes(cast("ComicBook", comic), errors) == 1
        assert errors.metadata_unreadable is not None

    def test_an_unreadable_metadata_file_has_its_own_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        errors = HashErrors(metadata_unreadable=(tmp_path / "metadata.json", "JSONDecodeError"))

        ComicsIntegrityChecker.print_hash_errors(errors)

        assert "cannot be read" in capsys.readouterr().out

    def test_a_panel_segments_file_that_is_not_text_is_a_fault(self, tmp_path: Path) -> None:
        segments_file = tmp_path / "001.json"
        segments_file.write_bytes(b'{"panels": "\xff\xfe"}')

        faults = check_panel_segments_file(
            segments_file,
            has_overall_bounds_override=False,
            panel_order_file=None,
            restored_image=None,
        )

        assert len(faults) == 1
        assert faults[0].startswith("Not valid JSON")

    def test_a_restored_image_that_will_not_open_is_a_fault(self, tmp_path: Path) -> None:
        segments_file = tmp_path / "001.json"
        segments_file.write_text("{}")
        restored_image = tmp_path / "001.png"
        restored_image.write_bytes(b"not a png")

        faults = check_panel_segments_file(
            segments_file,
            has_overall_bounds_override=False,
            panel_order_file=None,
            restored_image=restored_image,
        )

        assert len(faults) == 1
        assert faults[0].startswith("Cannot read the restored image")


class TestAPageFixedInBothExtensions:
    def test_the_png_half_of_a_pair_is_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "095.jpg").touch()
        png = tmp_path / "095.png"
        png.touch()

        assert is_second_of_fixes_pair(png, STANDARD_FIXES)

    def test_the_pair_is_reported_once_not_twice(self, tmp_path: Path) -> None:
        jpg = tmp_path / "095.jpg"
        jpg.touch()
        (tmp_path / "095.png").touch()

        assert not is_second_of_fixes_pair(jpg, STANDARD_FIXES)

    def test_a_lone_png_fix_is_not_a_pair(self, tmp_path: Path) -> None:
        png = tmp_path / "095.png"
        png.touch()

        assert not is_second_of_fixes_pair(png, STANDARD_FIXES)

    def test_the_upscayled_tree_has_no_pairs(self, tmp_path: Path) -> None:
        (tmp_path / "095.jpg").touch()
        png = tmp_path / "095.png"
        png.touch()

        assert not is_second_of_fixes_pair(png, UPSCAYLED_FIXES)

    def test_the_staging_gate_reports_the_pair_and_checks_the_other_collection(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def refuse(_db: object) -> dict:
            msg = 'Cannot have both .jpg and .png fixes file "095.jpg".'
            raise FixesPairError(msg)

        checked: list[object] = []
        monkeypatch.setattr(comics_integrity, "get_one_pager_staged_links", refuse)
        monkeypatch.setattr(comics_integrity, "get_cover_staged_links", lambda _db: {})
        monkeypatch.setattr(
            comics_integrity,
            "check_collection_staged_links",
            lambda collection, _links, **_kwargs: checked.append(collection) or 0,
        )

        assert make_checker(FakeDatabase()).check_staged_collection_links([]) == 1
        assert "Cannot check the staged links" in capsys.readouterr().out
        assert len(checked) == 1


class TestTheBatchBuildSurvivesATitleThatWillNotLoad:
    def test_the_titles_after_it_are_still_built(self, monkeypatch: pytest.MonkeyPatch) -> None:
        built: list[object] = []
        monkeypatch.setattr(
            batch_build_comics, "process_comic_book", lambda comic: built.append(comic) or 0
        )
        database = FakeDatabase(good_comic="the good comic")

        ret_code = batch_build_comics.process_comic_book_titles(
            cast("ComicsDatabase", database), [BAD_TITLE, GOOD_TITLE]
        )

        assert ret_code == 1
        assert built == ["the good comic"]


class TestTheRenameFixSurvivesATitleThatWillNotLoad:
    def test_a_value_error_is_a_load_error_not_a_crash(self) -> None:
        # The narrower tuple this replaced let a ValueError - a non-integer ini field -
        # through, against its own "one malformed ini must not abort" comment.
        database = FakeDatabase(titles=[BAD_TITLE])

        expected, load_errors = build_expected_artifacts(cast("ComicsDatabase", database))

        assert expected == {}
        assert len(load_errors) == 1
        assert BAD_TITLE in load_errors[0]
        assert "ValueError" in load_errors[0]


class StoredRow:
    def __init__(self, story: str) -> None:
        self.story = story


class TestTheCensorshipCsvSurvivesAStoryThatWillNotResolve:
    def test_every_unresolvable_story_is_kept_with_its_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def locate(_db: object, story: str) -> str:
            if story.startswith("Typo"):
                msg = f'no such story "{story}"'
                raise CensorshipCsvError(msg)
            return f"location of {story}"

        monkeypatch.setattr(censorship_csv, "locate_story", locate)
        rows = cast(
            "list[CensorshipFixRow]",
            [StoredRow("Typo One"), StoredRow("Real"), StoredRow("Real"), StoredRow("Typo Two")],
        )

        locations, unresolved = locate_stories(cast("ComicsDatabase", object()), rows)

        assert locations == {"Real": "location of Real"}
        assert list(unresolved) == ["Typo One", "Typo Two"]
