"""Tests for the two payment reports when a title's dates are not known.

Some covers have a payment entry although nothing is known of when they were submitted
or accepted, and the unknown parts are recorded as -1. Both reports fed those straight
into date arithmetic: `barks-yearly-payments` died in `cpi.inflate(value, -1)` before it
plotted anything, and `barks-chronological-titles` died building `date(-1, -1, -1)` for
any range holding 1951 or 1953. These run against the real payment tables, since the
unknown entries in them are the whole of the case.
"""

from __future__ import annotations

from barks_fantagraphics.barks_payments import BARKS_PAYMENTS
from barks_fantagraphics.comic_book_info import BARKS_TITLE_INFO

from barks_comic_building.query import barks_chronological_titles as chrono
from barks_comic_building.query import barks_yearly_payments as yearly

FIRST_BARKS_YEAR = 1942


def test_the_tables_still_hold_the_unknown_dates_these_tests_are_about() -> None:
    assert any(BARKS_TITLE_INFO[title].submitted_year == -1 for title in BARKS_PAYMENTS)
    assert any(payment.accepted_year == -1 for payment in BARKS_PAYMENTS.values())


def test_a_title_with_no_submission_year_is_left_out_of_the_yearly_totals() -> None:
    payments_by_year = yearly.sum_payments_by_year()

    assert payments_by_year
    assert min(payments_by_year) >= FIRST_BARKS_YEAR


def test_every_payment_entry_gets_an_accepted_date_without_raising() -> None:
    for title, payment in BARKS_PAYMENTS.items():
        assert chrono._accepted_date(BARKS_TITLE_INFO[title], payment)  # noqa: SLF001


def test_an_unknown_accepted_date_is_shown_as_unknown_and_not_flagged() -> None:
    title, payment = next(
        (title, payment) for title, payment in BARKS_PAYMENTS.items() if payment.accepted_year == -1
    )

    assert chrono._accepted_date(BARKS_TITLE_INFO[title], payment) == "?? ??? ????"  # noqa: SLF001


def test_a_known_date_is_formatted_and_an_unknown_day_is_tolerated() -> None:
    assert chrono._format_date(7, 3, 1951) == "07 Mar 1951"  # noqa: SLF001
    assert chrono._format_date(-1, 3, 1951) == "?? Mar 1951"  # noqa: SLF001
