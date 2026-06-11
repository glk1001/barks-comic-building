"""List Barks titles in chronological (submission) order within a year range."""

from datetime import date
from typing import Annotated

import typer
from barks_fantagraphics.barks_payments import BARKS_PAYMENTS, PaymentInfo
from barks_fantagraphics.comic_book_info import BARKS_TITLE_INFO, ComicBookInfo
from comic_utils.common_typer_options import LogLevelArg
from dateutil.relativedelta import relativedelta
from rich.console import Console
from rich.table import Table

from barks_comic_building.cli_setup import init_logging

APP_LOGGING_NAME = "chrn"

_MAX_ACCEPTANCE_GAP = relativedelta(months=6)

_MONTH_ABBREV = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def _format_date(day: int, month: int, year: int) -> str:
    """Format a (day, month, year) triple, tolerating an unknown (-1) day."""
    month_str = _MONTH_ABBREV[month] if 1 <= month <= 12 else "???"  # noqa: PLR2004
    day_str = "??" if day <= 0 else f"{day:02d}"
    return f"{day_str} {month_str} {year}"


def _submitted_date(info: ComicBookInfo) -> str:
    return _format_date(info.submitted_day, info.submitted_month, info.submitted_year)


def _issue_with_pub_date(info: ComicBookInfo) -> str:
    """Return the short issue title plus the publication (cover) month and year."""
    month_str = _MONTH_ABBREV[info.issue_month] if 1 <= info.issue_month <= 12 else "???"  # noqa: PLR2004
    return f"{info.get_short_issue_title()} ({month_str} {info.issue_year})"


def _submitted_sort_key(info: ComicBookInfo) -> tuple[int, int, int]:
    # An unknown day (-1) sorts to the start of its month.
    return info.submitted_year, info.submitted_month, max(info.submitted_day, 0)


def _is_dubious_accepted(info: ComicBookInfo, payment: PaymentInfo) -> bool:
    """Flag an accepted date that is before submission or more than 6 months after it."""
    submitted_day = 1 if info.submitted_day == -1 else info.submitted_day
    submitted_date = date(info.submitted_year, info.submitted_month, submitted_day)
    accepted_date = date(payment.accepted_year, payment.accepted_month, payment.accepted_day)

    return accepted_date < submitted_date or accepted_date > submitted_date + _MAX_ACCEPTANCE_GAP


def _accepted_date(info: ComicBookInfo, payment: PaymentInfo | None) -> str:
    if payment is None:
        return "-"
    accepted = _format_date(payment.accepted_day, payment.accepted_month, payment.accepted_year)
    if _is_dubious_accepted(info, payment):
        return f"[red]{accepted} *[/red]"
    return accepted


def _payment_str(payment: PaymentInfo | None) -> str:
    if payment is None:
        return "-"
    return f"${payment.payment:,.2f}"


app = typer.Typer()


@app.command(help="List Barks titles chronologically (by submission date) within a year range.")
def main(
    from_year: Annotated[int, typer.Argument(help="First submission year (inclusive).")],
    to_year: Annotated[int, typer.Argument(help="Last submission year (inclusive).")],
    log_level_str: LogLevelArg = "INFO",
) -> None:
    init_logging(APP_LOGGING_NAME, "barks-cmds.log", log_level_str)

    if from_year > to_year:
        msg = f"from_year ({from_year}) must not be greater than to_year ({to_year})."
        raise typer.BadParameter(msg)

    selected = [info for info in BARKS_TITLE_INFO if from_year <= info.submitted_year <= to_year]
    selected.sort(key=_submitted_sort_key)

    console = Console()
    table = Table(title=f"Barks Titles Submitted {from_year}-{to_year}")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Issue (Published)")
    table.add_column("Submitted")
    table.add_column("Payment", justify="right")
    table.add_column("Accepted")

    for info in selected:
        payment = BARKS_PAYMENTS.get(info.title)
        table.add_row(
            str(info.chronological_number),
            info.get_display_title(),
            _issue_with_pub_date(info),
            _submitted_date(info),
            _payment_str(payment),
            _accepted_date(info, payment),
        )

    console.print(table)
    console.print(f"[dim]{len(selected)} title(s).[/dim]")
    console.print("[dim]* accepted date is before submission or more than 6 months after it.[/dim]")


if __name__ == "__main__":
    app()
