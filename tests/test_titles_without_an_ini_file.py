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
from barks_fantagraphics.comic_book_info import COVERS

from barks_comic_building.query import verify_title

if TYPE_CHECKING:
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
