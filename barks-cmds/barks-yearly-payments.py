# ruff: noqa: T201

import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from barks_fantagraphics.barks_payments import BARKS_PAYMENTS
from barks_fantagraphics.barks_titles import BARKS_TITLE_INFO, ONE_PAGERS
from barks_fantagraphics.comics_cmd_args import CmdArgs
from cpi import inflate
from loguru import logger
from loguru_config import LoguruConfig
from yearly_graph import create_yearly_plot

APP_LOGGING_NAME = "ypay"

if __name__ == "__main__":
    cmd_args = CmdArgs("Barks yearly payments")
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variable accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = cmd_args.get_comics_database()

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
