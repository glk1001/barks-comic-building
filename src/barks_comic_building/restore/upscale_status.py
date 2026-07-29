"""Report how far the upscale has got, and what it has left to do.

Answers the questions the upscale run itself cannot: which volumes are finished under the
settings in force now, which were done under older settings and so need doing again, which
pages have no output at all, and how long the rest is going to take.

The state of a page comes from the files on disk and the recipe stamped into the upscayled
png, so this is accurate whether or not the ledger survived. The ledger only supplies the
timings behind the estimate, and the record of what failed and why.

The recipe depends on which backend would run, so the report is per backend: asking about
waifu2x while the library was made with Upscayl is what shows the whole library as stale,
and that is the answer, not a fault in the question.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Annotated, NamedTuple

import typer
from barks_fantagraphics.comic_book_info import is_non_comic_title
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from loguru import logger
from rich.console import Console
from rich.table import Table

from barks_comic_building.cli_setup import get_comic_titles, init_logging
from barks_comic_building.restore.batch_upscayl import SCALE
from barks_comic_building.restore.report_format import format_duration, shorten_volume_title
from barks_comic_building.restore.upscale_image import DEFAULT_UPSCALER, Upscaler, UpscalerArg
from barks_comic_building.restore.upscale_ledger import (
    UpscaleLedger,
    get_default_upscale_ledger_file,
    read_upscale_ledger,
)
from barks_comic_building.restore.upscale_recipe import get_current_recipe
from barks_comic_building.restore.upscale_state import UpscalePageState, get_upscale_page_status

APP_LOGGING_NAME = "usta"

# The order the state columns appear in, worst news last.
_REPORTED_STATES = (
    UpscalePageState.CURRENT,
    UpscalePageState.STALE,
    UpscalePageState.MISSING,
    UpscalePageState.LINKED,
    UpscalePageState.NO_SRCE,
)


class VolumeStatus(NamedTuple):
    """What a volume's restorable pages add up to."""

    volume: int
    title: str
    counts: Counter[UpscalePageState]

    @property
    def num_pages(self) -> int:
        """How many restorable pages the volume has."""
        return sum(self.counts.values())

    @property
    def num_to_do(self) -> int:
        """How many of them still need putting through the upscale."""
        return sum(count for state, count in self.counts.items() if state.needs_upscayling)


def get_title_status(
    comics_database: ComicsDatabase, title: str, current_recipe_id: str
) -> Counter[UpscalePageState]:
    """Return the state of every restorable page of a title.

    Args:
        comics_database: The comics database.
        title: The title to look at.
        current_recipe_id: The id of the recipe the upscale would use now.

    Returns:
        How many pages are in each state.

    """
    comic = comics_database.get_comic_book(title)

    srce_files = comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
    upscayl_files = comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)

    counts: Counter[UpscalePageState] = Counter()
    for (srce_file, _srce_mod), (dest_file, _is_mod_file) in zip(
        srce_files, upscayl_files, strict=True
    ):
        status = get_upscale_page_status(Path(srce_file), Path(dest_file), current_recipe_id)
        counts[status.state] += 1

    return counts


def get_status_by_volume(
    comics_database: ComicsDatabase, titles: list[str], current_recipe_id: str
) -> list[VolumeStatus]:
    """Return the state of every restorable page, gathered by volume.

    Args:
        comics_database: The comics database.
        titles: The titles to look at.
        current_recipe_id: The id of the recipe the upscale would use now.

    Returns:
        One entry per volume, in volume order.

    """
    by_volume: dict[int, Counter[UpscalePageState]] = {}

    for title in titles:
        if is_non_comic_title(title):
            # Copied through rather than upscayled, so it has no recipe to compare.
            continue

        volume = comics_database.get_fanta_volume_int(title)
        by_volume.setdefault(volume, Counter()).update(
            get_title_status(comics_database, title, current_recipe_id)
        )

    return [
        VolumeStatus(
            volume=volume,
            title=comics_database.get_fantagraphics_volume_title(volume),
            counts=counts,
        )
        for volume, counts in sorted(by_volume.items())
    ]


def _get_seconds_per_page(ledger: UpscaleLedger, current_recipe_id: str) -> float:
    """Return the measured cost of a page, preferring pages made with this recipe."""
    stats = ledger.timing_stats(current_recipe_id) or ledger.timing_stats()

    return stats.mean_seconds if stats else 0.0


def print_status_table(
    statuses: list[VolumeStatus], seconds_per_page: float, upscaler: Upscaler, recipe_id: str
) -> None:
    """Print the per-volume report.

    Args:
        statuses: The volumes to report on.
        seconds_per_page: Measured cost of a page, or 0 when nothing has been measured.
        upscaler: The backend the report is about.
        recipe_id: The id of the recipe the upscale would use now.

    """
    console = Console()

    table = Table(title=f"Upscale status - {upscaler}, current recipe {recipe_id}")
    table.add_column("Vol", justify="right")
    table.add_column("Title", no_wrap=True)
    table.add_column("Pages", justify="right")
    table.add_column("Current", justify="right", style="green")
    table.add_column("Stale", justify="right", style="yellow")
    table.add_column("Missing", justify="right", style="red")
    table.add_column("Linked", justify="right", style="dim")
    table.add_column("No srce", justify="right", style="dim")
    table.add_column("Est. left", justify="right")

    for status in statuses:
        table.add_row(
            str(status.volume),
            shorten_volume_title(status.title),
            str(status.num_pages),
            *(str(status.counts[state] or "") for state in _REPORTED_STATES),
            format_duration(status.num_to_do * seconds_per_page),
        )

    totals: Counter[UpscalePageState] = Counter()
    for status in statuses:
        totals.update(status.counts)
    num_to_do = sum(count for state, count in totals.items() if state.needs_upscayling)

    table.add_section()
    table.add_row(
        "",
        f"[bold]{len(statuses)} volume(s)[/bold]",
        f"[bold]{sum(totals.values())}[/bold]",
        *(f"[bold]{totals[state] or ''}[/bold]" for state in _REPORTED_STATES),
        f"[bold]{format_duration(num_to_do * seconds_per_page)}[/bold]",
    )

    console.print(table)

    if seconds_per_page:
        console.print(f"{num_to_do} page(s) to do at a measured {int(seconds_per_page)}s each.")
    else:
        console.print(
            f"{num_to_do} page(s) to do. No timings recorded yet, so no estimate -"
            " run a volume and the ledger will have one.",
        )

    if totals[UpscalePageState.LINKED]:
        console.print(
            f"{totals[UpscalePageState.LINKED]} page(s) are symlinks to other volumes'"
            " pages and are upscayled as part of those volumes.",
        )


def print_failures(ledger: UpscaleLedger) -> None:
    """Print the pages whose most recent attempt failed, and why.

    The reason is worth the width: a page Upscayl blacked out and a page it never got to
    read the same from the outcome alone.

    Args:
        ledger: The parsed ledger.

    """
    failures = [record for record in ledger.latest_by_page().values() if not record.is_ok]

    console = Console()
    if not failures:
        console.print("No failed pages recorded.")
        return

    table = Table(title=f"{len(failures)} failed page(s)", show_lines=True)
    table.add_column("Vol", justify="right")
    table.add_column("Title")
    table.add_column("Page")
    table.add_column("When")
    table.add_column("Error")

    for record in sorted(failures, key=lambda r: (r.volume, r.title, r.page)):
        table.add_row(
            str(record.volume),
            record.title,
            record.page,
            record.finished,
            record.error or "unknown",
        )

    console.print(table)


def print_json(
    statuses: list[VolumeStatus], seconds_per_page: float, upscaler: Upscaler, recipe_id: str
) -> None:
    """Print the report as json, for scripting.

    Args:
        statuses: The volumes to report on.
        seconds_per_page: Measured cost of a page, or 0 when nothing has been measured.
        upscaler: The backend the report is about.
        recipe_id: The id of the recipe the upscale would use now.

    """
    report = {
        "upscaler": str(upscaler),
        "recipe_id": recipe_id,
        "seconds_per_page": round(seconds_per_page, 1),
        "volumes": [
            {
                "volume": status.volume,
                "title": status.title,
                "pages": status.num_pages,
                "to_do": status.num_to_do,
                "states": {str(state): status.counts[state] for state in _REPORTED_STATES},
            }
            for status in statuses
        ],
    }

    print(json.dumps(report, indent=2))  # noqa: T201


app = typer.Typer()


@app.command(help="Report what the upscale has done and what is left")
def main(  # noqa: PLR0913
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    upscaler: UpscalerArg = DEFAULT_UPSCALER,
    log_level_str: LogLevelArg = "WARNING",
    ledger_file: Annotated[
        Path | None,
        typer.Option("--ledger", help="The ledger to take timings and failures from."),
    ] = None,
    failed: bool = typer.Option(
        default=False,
        help="List the pages whose last attempt failed, and why, instead of the summary.",
    ),
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the summary as json."),
    ] = False,
) -> None:
    init_logging(APP_LOGGING_NAME, "upscale-status.log", log_level_str)

    ledger = read_upscale_ledger(ledger_file or get_default_upscale_ledger_file())

    if failed:
        print_failures(ledger)
        return

    recipe = get_current_recipe(upscaler, SCALE)
    logger.info(f"Current recipe {recipe.recipe_id}: {recipe.as_json()}")

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    statuses = get_status_by_volume(comics_database, titles, recipe.recipe_id)
    seconds_per_page = _get_seconds_per_page(ledger, recipe.recipe_id)

    if as_json:
        print_json(statuses, seconds_per_page, upscaler, recipe.recipe_id)
        return

    print_status_table(statuses, seconds_per_page, upscaler, recipe.recipe_id)


if __name__ == "__main__":
    app()
