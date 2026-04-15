# ruff: noqa: T201

from collections import defaultdict
from datetime import datetime

import typer
from barks_fantagraphics.barks_payments import BARKS_PAYMENTS
from barks_fantagraphics.comic_book_info import BARKS_TITLE_INFO, ONE_PAGERS
from comic_utils.common_typer_options import LogLevelArg
from cpi import inflate

from barks_comic_building.cli_setup import init_logging
from barks_comic_building.query.yearly_graph import create_yearly_plot

APP_LOGGING_NAME = "ypay"

app = typer.Typer()


@app.command(help="Barks yearly payments")
def main(log_level_str: LogLevelArg = "DEBUG") -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    payments_by_year = defaultdict(int)
    for title in BARKS_PAYMENTS:
        title_payment_info = BARKS_PAYMENTS[title]

        payment = 0 if title in ONE_PAGERS else title_payment_info.payment

        submitted_year = BARKS_TITLE_INFO[title].submitted_year
        payments_by_year[submitted_year] += payment

    for year in payments_by_year:
        print(f"{year}: {payments_by_year[year]}")

    years = sorted(payments_by_year)
    values_data = [inflate(payments_by_year[y], y) for y in years]

    current_year = datetime.now().astimezone().year
    title = f"Yearly Payments from {years[0]} to {years[-1]} (Adjusted to {current_year})"

    print(f"Plotting {len(years)} data points...")

    create_yearly_plot(
        title,
        years=years,
        values=values_data,
        output_filename="/tmp/barks-yearly-payments.png",  # noqa: S108
        width_px=1000,
        height_px=732,
        dpi=100,  # A common DPI for screen resolutions
    )


if __name__ == "__main__":
    app()
