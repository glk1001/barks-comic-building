# ruff: noqa: T201

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import typer
from barks_fantagraphics.barks_payments import BARKS_PAYMENTS
from barks_fantagraphics.barks_titles import BARKS_TITLE_INFO, ONE_PAGERS
from comic_utils.common_typer_options import LogLevelArg
from cpi import inflate
from loguru_config import LoguruConfig

import barks_comic_building.log_setup as _log_setup
from barks_comic_building.query.yearly_graph import create_yearly_plot

APP_LOGGING_NAME = "ypay"

_RESOURCES = Path(__file__).parent.parent / "resources"

app = typer.Typer()


@app.command(help="Barks yearly payments")
def main(log_level_str: LogLevelArg = "DEBUG") -> None:
    _log_setup.log_level = log_level_str
    _log_setup.log_filename = "barks-cmds.log"
    _log_setup.APP_LOGGING_NAME = APP_LOGGING_NAME
    LoguruConfig.load(_RESOURCES / "log-config.yaml")

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
