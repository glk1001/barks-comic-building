"""Tests for the tools that take a title, given a title that has no ini file of its own.

The comics database only knows the titles it has an ini file for. A one-pager and a cover
are pages of the two collections, and a story nobody has worked on yet has no ini file
either, so that is 480 real titles the database cannot open - and two tools treated "the
database cannot open it" as the answer to a different question.

`barks-verify-title` took it to mean the title was wrong: "If the Hat Fits" was "not a
valid title. Did you mean: In the Swim". And the tools that open a page built its path
from the title's home volume, where a one-pager that belongs to no story has never had a
restored file: it is restored only as a page of "All One-Pagers", in the collection's
volume, so `barks-show-title-page` said a long-restored page could not be found.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from barks_fantagraphics.barks_titles import ENUM_TO_STR_TITLE, Titles
from barks_fantagraphics.comic_book_info import (
    COVERS,
    ONE_PAGER_COLLECTION_PAGE_BASE,
    ONE_PAGER_COLLECTION_VOLUME,
    ONE_PAGERS,
    get_located_one_pagers,
    get_one_pager_collection_page_num,
    get_one_pager_fanta_vol_and_page,
)

from barks_comic_building.query import verify_title
from barks_comic_building.query.page_files import get_title_page_file, get_volume_page_file

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comics_database import ComicsDatabase

ONE_PAGER = Titles.IF_THE_HAT_FITS
UNCONFIGURED_STORY = Titles.PAWNS_OF_THE_LOUP_GAROU  # cspell:disable-line


class NoIniFilesDatabase:
    """A database with no ini files: every title is one it cannot open."""

    def is_story_title(self, _title: str) -> tuple[bool, str]:
        # What the real one suggests for a one-pager: the nearest title *it* knows.
        return False, "In the Swim"


def verdict(title: str) -> str:
    return verify_title.get_story_title_verdict(cast("ComicsDatabase", NoIniFilesDatabase()), title)


class TestVerifyingATitle:
    def test_a_one_pager_is_a_valid_title(self) -> None:
        assert verdict(ENUM_TO_STR_TITLE[ONE_PAGER]) == (
            'This is a valid title: "(If the Hat Fits)" [FC 147], FANTA_05 (a one-pager).'
        )

    def test_a_cover_is_a_valid_title(self) -> None:
        line = verdict(ENUM_TO_STR_TITLE[COVERS[0]])

        assert line.startswith("This is a valid title: ")
        assert line.endswith("(a cover).")

    def test_a_story_with_no_ini_file_is_a_valid_title(self) -> None:
        line = verdict(ENUM_TO_STR_TITLE[UNCONFIGURED_STORY])

        assert line.startswith("This is a valid title: ")
        assert line.endswith("(a story with no ini file yet).")

    def test_a_title_in_no_volume_says_so_instead_of_raising(self) -> None:
        assert "no Fantagraphics volume" in verdict(ENUM_TO_STR_TITLE[UNCONFIGURED_STORY])

    def test_a_misspelling_is_matched_against_every_title(self) -> None:
        # Not against the database's titles, which hold no one-pager to suggest.
        assert verdict("If the Hat Fist") == (
            '"If the Hat Fist" is not a valid title. Did you mean: "If the Hat Fits".'
        )

    def test_nonsense_is_close_to_nothing(self) -> None:
        assert verdict("0000 0000 0000") == (
            '"0000 0000 0000" is not a valid title. Cannot find anything close to this.'
        )

    @pytest.mark.parametrize(
        ("title", "kind"),
        [
            (ONE_PAGER, "a one-pager"),
            (COVERS[0], "a cover"),
            (UNCONFIGURED_STORY, "a story with no ini file yet"),
        ],
        ids=["one-pager", "cover", "story"],
    )
    def test_each_kind_of_title_is_named(self, title: Titles, kind: str) -> None:
        assert verify_title.get_title_kind(title) == kind


class TestFindingATitlesPage:
    """One tree of volumes under a temporary directory, as `get_volume_dir` would give it."""

    @pytest.fixture
    def one_pager(self) -> Titles:
        return next(iter(sorted(ONE_PAGERS, key=lambda title: title.value)))

    @staticmethod
    def volume_dir(tmp_path: Path, volume: int) -> Path:
        return tmp_path / f"vol-{volume:02d}"

    @staticmethod
    def home_file(tmp_path: Path, title: Titles) -> Path:
        volume, page = get_one_pager_fanta_vol_and_page(title)
        assert volume is not None
        assert page is not None
        return tmp_path / f"vol-{volume:02d}" / f"{page:03d}.png"

    @staticmethod
    def collection_file(tmp_path: Path, title: Titles) -> Path:
        collection_page_num = get_one_pager_collection_page_num(title)
        assert collection_page_num is not None
        page = ONE_PAGER_COLLECTION_PAGE_BASE + collection_page_num - 1
        return tmp_path / f"vol-{ONE_PAGER_COLLECTION_VOLUME:02d}" / f"{page:03d}.png"

    def find(self, tmp_path: Path, title: Titles) -> Path:
        volume, page = get_one_pager_fanta_vol_and_page(title)
        assert volume is not None
        assert page is not None
        return get_title_page_file(
            ENUM_TO_STR_TITLE[title],
            volume,
            f"{page:03d}",
            lambda vol: self.volume_dir(tmp_path, vol),
            ".png",
        )

    def test_a_page_of_a_story_is_the_file_in_its_own_volume(self, tmp_path: Path) -> None:
        found = get_title_page_file(
            "Lost in the Andes!", 7, "227", lambda vol: self.volume_dir(tmp_path, vol), ".json"
        )

        assert found == tmp_path / "vol-07" / "227.json"

    def test_a_one_pager_restored_only_in_the_collection_is_found_there(
        self, tmp_path: Path, one_pager: Titles
    ) -> None:
        collection_file = self.collection_file(tmp_path, one_pager)
        collection_file.parent.mkdir(parents=True)
        collection_file.touch()

        assert self.find(tmp_path, one_pager) == collection_file

    def test_a_one_pager_in_its_home_volume_is_found_there_first(
        self, tmp_path: Path, one_pager: Titles
    ) -> None:
        for file in (
            self.home_file(tmp_path, one_pager),
            self.collection_file(tmp_path, one_pager),
        ):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.touch()

        assert self.find(tmp_path, one_pager) == self.home_file(tmp_path, one_pager)

    def test_a_one_pager_in_neither_place_is_named_by_its_home_volume(
        self, tmp_path: Path, one_pager: Titles
    ) -> None:
        assert self.find(tmp_path, one_pager) == self.home_file(tmp_path, one_pager)


class TestFindingAVolumesPage:
    """`barks-show-volume-page` is given a volume and a page, and no title."""

    @pytest.fixture
    def one_pager(self) -> Titles:
        return next(iter(sorted(ONE_PAGERS, key=lambda title: title.value)))

    @staticmethod
    def find(tmp_path: Path, volume: int, page_num: int) -> Path:
        return get_volume_page_file(
            volume, page_num, lambda vol: tmp_path / f"vol-{vol:02d}", ".png"
        )

    def find_one_pager(self, tmp_path: Path, title: Titles) -> Path:
        volume, page_num = get_one_pager_fanta_vol_and_page(title)
        assert volume is not None
        assert page_num is not None
        return self.find(tmp_path, volume, page_num)

    def test_a_page_that_is_no_one_pager_is_the_file_in_the_volume(self, tmp_path: Path) -> None:
        assert self.find(tmp_path, 7, 5) == tmp_path / "vol-07" / "005.png"

    def test_a_one_pagers_page_restored_only_in_the_collection_is_found_there(
        self, tmp_path: Path, one_pager: Titles
    ) -> None:
        collection_file = TestFindingATitlesPage.collection_file(tmp_path, one_pager)
        collection_file.parent.mkdir(parents=True)
        collection_file.touch()

        assert self.find_one_pager(tmp_path, one_pager) == collection_file

    def test_a_one_pagers_page_in_the_volume_is_found_there_first(
        self, tmp_path: Path, one_pager: Titles
    ) -> None:
        home_file = TestFindingATitlesPage.home_file(tmp_path, one_pager)
        for file in (home_file, TestFindingATitlesPage.collection_file(tmp_path, one_pager)):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.touch()

        assert self.find_one_pager(tmp_path, one_pager) == home_file

    def test_a_one_pagers_page_in_neither_place_is_named_by_the_volume_asked_for(
        self, tmp_path: Path, one_pager: Titles
    ) -> None:
        assert self.find_one_pager(tmp_path, one_pager) == TestFindingATitlesPage.home_file(
            tmp_path, one_pager
        )

    def test_no_two_one_pagers_share_a_place_in_the_books(self) -> None:
        # The lookup returns the first one-pager at a place, so a shared place would
        # silently open the wrong one.
        places = [get_one_pager_fanta_vol_and_page(title) for title in get_located_one_pagers()]

        assert len(set(places)) == len(places)
