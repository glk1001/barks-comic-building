"""Tests for what the two yearly charts add up.

Both charts ran and both were wrong. The payments chart took every unknown payment,
recorded as -1, off its year's total as if it were money, and left every one-pager out.
The page-count chart mixed units - every page of a built comic for one title, story pages
for the next - read a table of placeholder counts ahead of the titles' own page lists
long after those titles were configured, and counted the two synthetic collections as
339 pages drawn in 1982, which is every one-pager a second time.
"""

from __future__ import annotations

import pytest
from barks_fantagraphics.barks_payments import BARKS_PAYMENTS
from barks_fantagraphics.comic_book_info import BARKS_TITLE_INFO, ONE_PAGERS

from barks_comic_building.query import barks_yearly_payments as payments


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
