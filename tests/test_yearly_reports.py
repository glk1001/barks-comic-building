"""Tests for what the two yearly charts add up.

Both charts ran and both were wrong. The payments chart took every unknown payment,
recorded as -1, off its year's total as if it were money, and left every one-pager out.
The page-count chart mixed units - every page of a built comic for one title, story pages
for the next - read a table of placeholder counts ahead of the titles' own page lists
long after those titles were configured, and counted the two synthetic collections as
339 pages drawn in 1982, which is every one-pager a second time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest
from barks_fantagraphics.barks_payments import BARKS_PAYMENTS
from barks_fantagraphics.barks_titles import ENUM_TO_STR_TITLE, Titles
from barks_fantagraphics.comic_book_info import (
    BARKS_TITLE_INFO,
    COVERS,
    NON_COMIC_TITLES,
    ONE_PAGERS,
    SYNTHETIC_TITLES,
)
from barks_fantagraphics.comics_consts import PageType
from barks_fantagraphics.comics_database import TitleNotFoundError
from comic_utils.cpi_calculator import get_latest_year
from comic_utils.cpi_table import ANNUAL_CPI

from barks_comic_building.query import barks_yearly_page_count as page_count
from barks_comic_building.query import barks_yearly_payments as payments

if TYPE_CHECKING:
    from barks_fantagraphics.comics_database import ComicsDatabase

CONFIGURED = Titles.LOST_IN_THE_ANDES
# A built comic: a title page, the story, and a page of back matter.
CONFIGURED_PAGE_TYPES = [
    PageType.TITLE,
    *[PageType.BODY] * 32,
    PageType.BACK_MATTER,
]
STORY_PAGES = 32

IN_THE_TABLE = Titles.KING_SCROOGE_THE_FIRST
IN_NEITHER = Titles.PAWNS_OF_THE_LOUP_GAROU  # cspell:disable-line


@dataclass
class FakePage:
    page_type: PageType


@dataclass
class FakeComic:
    page_images_in_order: list[FakePage]


class FakeDatabase:
    """A database in which the given titles, and only those, have an ini file."""

    def __init__(self, configured: dict[Titles, list[PageType]]) -> None:
        self._configured = {
            ENUM_TO_STR_TITLE[title]: FakeComic([FakePage(t) for t in page_types])
            for title, page_types in configured.items()
        }

    def get_comic_book(self, title: str) -> FakeComic:
        if title not in self._configured:
            msg = f'Could not find title "{title}".'
            raise TitleNotFoundError(msg, title)
        return self._configured[title]


def database(configured: dict[Titles, list[PageType]] | None = None) -> ComicsDatabase:
    return cast("ComicsDatabase", FakeDatabase(configured or {}))


class TestYearlyPayments:
    def test_an_unknown_payment_is_not_taken_off_the_total(self) -> None:
        assert any(payment.payment < 0 for payment in BARKS_PAYMENTS.values())

        by_year = payments.sum_payments_by_year()

        known = [
            payment.payment
            for title, payment in BARKS_PAYMENTS.items()
            if payment.payment >= 0 and BARKS_TITLE_INFO[title].submitted_year > 0
        ]
        assert sum(by_year.values()) == pytest.approx(sum(known))

    def test_one_pagers_are_counted(self) -> None:
        one_pager, payment = next(
            (title, payment)
            for title, payment in BARKS_PAYMENTS.items()
            if title in ONE_PAGERS and payment.payment > 0
        )
        year = BARKS_TITLE_INFO[one_pager].submitted_year
        rest_of_the_year = sum(
            other.payment
            for title, other in BARKS_PAYMENTS.items()
            if title != one_pager
            and other.payment >= 0
            and BARKS_TITLE_INFO[title].submitted_year == year
        )

        assert payments.sum_payments_by_year()[year] == pytest.approx(
            rest_of_the_year + payment.payment
        )

    def test_each_total_is_scaled_by_the_two_years_price_levels(self) -> None:
        adjusted = payments.adjust_to_year({1950: 100.0, 1960: 200.0}, 1960)

        assert adjusted[1950] == pytest.approx(100.0 * ANNUAL_CPI[1960] / ANNUAL_CPI[1950])
        assert adjusted[1960] == pytest.approx(200.0)

    def test_every_payment_year_can_be_adjusted_to_the_latest_one(self) -> None:
        by_year = payments.sum_payments_by_year()

        adjusted = payments.adjust_to_year(by_year, get_latest_year())

        assert adjusted.keys() == by_year.keys()
        assert all(adjusted[year] >= by_year[year] for year in by_year)

    def test_a_year_the_table_does_not_have_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="No CPI data for 1800"):
            payments.adjust_to_year({1800: 100.0}, 1960)


class TestStoryPageCount:
    def test_a_configured_title_counts_only_its_story_pages(self) -> None:
        db = database({CONFIGURED: CONFIGURED_PAGE_TYPES})

        assert page_count.get_story_page_count(db, CONFIGURED) == STORY_PAGES

    def test_a_configured_title_is_not_answered_for_by_the_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(page_count.UNCONFIGURED_PAGE_COUNTS, CONFIGURED, 10)
        db = database({CONFIGURED: CONFIGURED_PAGE_TYPES})

        assert page_count.get_story_page_count(db, CONFIGURED) == STORY_PAGES

    def test_an_unconfigured_title_takes_its_count_from_the_table(self) -> None:
        assert (
            page_count.get_story_page_count(database(), IN_THE_TABLE)
            == (page_count.UNCONFIGURED_PAGE_COUNTS[IN_THE_TABLE])
        )

    def test_an_unconfigured_title_missing_from_the_table_has_no_count(self) -> None:
        assert IN_NEITHER not in page_count.UNCONFIGURED_PAGE_COUNTS

        assert page_count.get_story_page_count(database(), IN_NEITHER) is None

    def test_a_one_pager_is_one_page(self) -> None:
        assert page_count.get_story_page_count(database(), next(iter(ONE_PAGERS))) == 1

    @pytest.mark.parametrize(
        "title",
        [SYNTHETIC_TITLES[0], SYNTHETIC_TITLES[-1], COVERS[0], NON_COMIC_TITLES[0]],
        ids=lambda title: title.name,
    )
    def test_a_title_that_is_not_a_story_has_no_count(self, title: Titles) -> None:
        # Given an ini file, as the two collections really have: it must still not count.
        db = database({title: CONFIGURED_PAGE_TYPES})

        assert page_count.get_story_page_count(db, title) is None


class TestPagesByYear:
    def test_each_year_is_its_one_pagers_plus_its_stories(self) -> None:
        by_year, _uncounted = page_count.sum_pages_by_year(
            database({CONFIGURED: CONFIGURED_PAGE_TYPES})
        )

        info = BARKS_TITLE_INFO[CONFIGURED]
        others = sum(
            page_count.get_story_page_count(database(), other.title) or 0
            for other in BARKS_TITLE_INFO
            if other.submitted_year == info.submitted_year and other.title != CONFIGURED
        )
        assert by_year[info.submitted_year] == others + STORY_PAGES

    def test_only_a_year_with_a_story_in_it_has_a_count(self) -> None:
        by_year, _uncounted = page_count.sum_pages_by_year(database())

        story_years = {
            info.submitted_year
            for info in BARKS_TITLE_INFO
            if page_count.get_story_page_count(database(), info.title) is not None
        }
        assert set(by_year) == story_years
        assert min(by_year) > 0

    def test_a_story_with_no_count_anywhere_is_reported_and_nothing_else_is(self) -> None:
        _by_year, uncounted = page_count.sum_pages_by_year(database())

        assert IN_NEITHER in uncounted
        assert not any(
            title in ONE_PAGERS
            or title in COVERS
            or title in SYNTHETIC_TITLES
            or title in NON_COMIC_TITLES
            for title in uncounted
        )
