"""Plot what Barks was paid for the work he submitted in each year, in today's money."""
# ruff: noqa: T201

from collections import defaultdict

import typer
from barks_fantagraphics.barks_payments import BARKS_PAYMENTS
from barks_fantagraphics.comic_book_info import BARKS_TITLE_INFO
from comic_utils.common_typer_options import LogLevelArg
from comic_utils.cpi_calculator import get_adjusted_usd, get_latest_year

from barks_comic_building.cli_setup import init_logging
from barks_comic_building.query.yearly_graph import show_yearly_report_plot

APP_LOGGING_NAME = "ypay"

UNKNOWN_YEAR = -1

app = typer.Typer()


def sum_payments_by_year() -> dict[int, float]:
    """Total what Barks was paid for the work he submitted in each year.

    Every kind of title is counted, one-pagers included. A title whose submission year
    is unknown is left out: it has no year to be counted under, and no year to inflate
    its payment from. So is one whose payment is unknown, which is recorded as a negative
    amount and would otherwise be taken off the year's total as if it were money.

    Returns:
        The total payment for each submission year, in the dollars of that year.

    """
    # Annotated float, defaulted int: a few payments are fractional, but the default
    # stays 0 rather than 0.0 so the printed totals read as they always have.
    payments_by_year: defaultdict[int, float] = defaultdict(int)
    for title, title_payment_info in BARKS_PAYMENTS.items():
        submitted_year = BARKS_TITLE_INFO[title].submitted_year
        if submitted_year == UNKNOWN_YEAR:
            continue

        if title_payment_info.payment < 0:
            continue

        payments_by_year[submitted_year] += title_payment_info.payment

    return dict(payments_by_year)


def adjust_to_year(payments_by_year: dict[int, float], to_year: int) -> dict[int, float]:
    """Put each year's total into the dollars of one year.

    Args:
        payments_by_year: The total payment for each year, in the dollars of that year.
        to_year: The year whose dollars the totals are converted to.

    Returns:
        The total for each year, in the dollars of `to_year`.

    Raises:
        ValueError: If the CPI table has no figure for one of the years.

    """
    return {
        year: get_adjusted_usd(payment, year, to_year) for year, payment in payments_by_year.items()
    }


@app.command(help="Barks yearly payments")
def main(log_level_str: LogLevelArg = "DEBUG") -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    payments_by_year = sum_payments_by_year()

    for year in payments_by_year:
        print(f"{year}: {payments_by_year[year]}")

    years = sorted(payments_by_year)
    # To the latest year the CPI table covers, which is the year the title has to name:
    # the chart once read "Adjusted to 2026" over 2025 dollars. The table is the one the
    # reader uses (comic_utils.cpi_table), so the two give the same figures.
    latest_year = get_latest_year()
    adjusted = adjust_to_year(payments_by_year, latest_year)
    values_data = [adjusted[y] for y in years]

    title = f"Yearly Payments from {years[0]} to {years[-1]} (Adjusted to {latest_year})"

    show_yearly_report_plot(
        title,
        years,
        values_data,
        "/tmp/barks-yearly-payments.png",  # noqa: S108
    )


if __name__ == "__main__":
    app()
