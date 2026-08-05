"""Report how far the restore has got, and what it has left to do.

Answers the questions the restore run itself cannot: which volumes are finished under the
settings in force now, which were done under older settings and so need doing again, which
pages are half written, and how long the rest is going to take.

The state of a page comes from the files on disk and the recipe stamped into the restored
png, so this is accurate whether or not the ledger survived. The ledger only supplies the
timings behind the estimate, and the record of what failed and where.
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
from barks_comic_building.restore.batch_restore_pipeline import SCALE
from barks_comic_building.restore.page_state import PageState, get_page_status
from barks_comic_building.restore.report_format import format_duration, shorten_volume_title
from barks_comic_building.restore.restore_ledger import (
    Ledger,
    get_default_ledger_file,
    read_ledger,
)
from barks_comic_building.restore.restore_recipe import get_current_recipe

APP_LOGGING_NAME = "rsta"

# The order the state columns appear in, worst news last.
_REPORTED_STATES = (
    PageState.CURRENT,
    PageState.STALE,
    PageState.INCOMPLETE,
    PageState.MISSING,
    PageState.HAND_RESTORED,
    PageState.LINKED,
    PageState.NO_SRCE,
)


class VolumeStatus(NamedTuple):
    """What a volume's restorable pages add up to."""

    volume: int
    title: str
    counts: Counter[PageState]

    @property
    def num_pages(self) -> int:
        """How many restorable pages the volume has."""
        return sum(self.counts.values())

    @property
    def num_to_do(self) -> int:
        """How many of them still need putting through the pipeline."""
        return sum(count for state, count in self.counts.items() if state.needs_restoring)


def get_title_status(
    comics_database: ComicsDatabase, title: str, current_recipe_id: str
) -> Counter[PageState]:
    """Return the state of every restorable page of a title.

    Args:
        comics_database: The comics database.
        title: The title to look at.
        current_recipe_id: The id of the recipe the pipeline would use now.

    Returns:
        How many pages are in each state.

    """
    comic = comics_database.get_comic_book(title)

    srce_upscayl_files = comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)
    dest_restored_files = comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)
    dest_restored_upscayled_files = comic.get_srce_restored_upscayled_story_files(
        RESTORABLE_PAGE_TYPES,
    )
    dest_restored_svg_files = comic.get_srce_restored_svg_story_files(RESTORABLE_PAGE_TYPES)

    counts: Counter[PageState] = Counter()
    for upscayl_file, restored_file, upscayled_restored_file, svg_file in zip(
        srce_upscayl_files,
        dest_restored_files,
        dest_restored_upscayled_files,
        dest_restored_svg_files,
        strict=True,
    ):
        status = get_page_status(
            Path(upscayl_file[0]),
            Path(restored_file),
            Path(upscayled_restored_file),
            Path(svg_file),
            current_recipe_id,
            is_hand_restored=comic.is_hand_restored(Path(restored_file).stem),
        )
        counts[status.state] += 1

    return counts


def get_status_by_volume(
    comics_database: ComicsDatabase, titles: list[str], current_recipe_id: str
) -> list[VolumeStatus]:
    """Return the state of every restorable page, gathered by volume.

    Args:
        comics_database: The comics database.
        titles: The titles to look at.
        current_recipe_id: The id of the recipe the pipeline would use now.

    Returns:
        One entry per volume, in volume order.

    """
    by_volume: dict[int, Counter[PageState]] = {}

    for title in titles:
        if is_non_comic_title(title):
            # Copied through rather than restored, so it has no recipe to compare.
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


def _get_seconds_per_page(ledger: Ledger, current_recipe_id: str) -> float:
    """Return the measured cost of a page, preferring pages made with this recipe."""
    stats = ledger.timing_stats(current_recipe_id) or ledger.timing_stats()

    return stats.mean_seconds if stats else 0.0


def print_status_table(
    statuses: list[VolumeStatus], seconds_per_page: float, current_recipe_id: str
) -> None:
    """Print the per-volume report.

    Args:
        statuses: The volumes to report on.
        seconds_per_page: Measured cost of a page, or 0 when nothing has been measured.
        current_recipe_id: The id of the recipe the pipeline would use now.

    """
    console = Console()

    table = Table(title=f"Restore status - current recipe {current_recipe_id}")
    table.add_column("Vol", justify="right")
    table.add_column("Title", no_wrap=True)
    table.add_column("Pages", justify="right")
    table.add_column("Current", justify="right", style="green")
    table.add_column("Stale", justify="right", style="yellow")
    table.add_column("Incomplete", justify="right", style="red")
    table.add_column("Missing", justify="right", style="red")
    table.add_column("Hand", justify="right", style="dim")
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

    totals: Counter[PageState] = Counter()
    for status in statuses:
        totals.update(status.counts)
    num_to_do = sum(count for state, count in totals.items() if state.needs_restoring)

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
        console.print(
            f"{num_to_do} page(s) to do at a measured {int(seconds_per_page)}s each.",
        )
    else:
        console.print(
            f"{num_to_do} page(s) to do. No timings recorded yet, so no estimate -"
            " run a batch and the ledger will have one.",
        )

    if totals[PageState.LINKED]:
        console.print(
            f"{totals[PageState.LINKED]} page(s) are symlinks to other volumes' pages"
            " and are restored as part of those volumes.",
        )

    if totals[PageState.HAND_RESTORED]:
        console.print(
            f"{totals[PageState.HAND_RESTORED]} page(s) were restored by hand and are never"
            " put through the pipeline - the hand restoration is the finished page.",
        )


def print_step_breakdown(ledger: Ledger, current_recipe_id: str) -> None:
    """Print where the time goes, per pipeline step.

    Args:
        ledger: The parsed ledger.
        current_recipe_id: Only count pages made with this recipe.

    """
    stats = ledger.timing_stats(current_recipe_id) or ledger.timing_stats()
    console = Console()

    if stats is None:
        console.print("No timings recorded yet.")
        return

    # Steps run several pages at once, so these are contended per-page means and add up
    # to well over the wall clock a page actually costs. They rank the steps; they do not
    # sum to the total.
    total = sum(stats.step_mean_seconds.values()) or 1.0

    table = Table(title=f"Mean seconds per step over {stats.count} page(s)")
    table.add_column("Step")
    table.add_column("Mean s", justify="right")
    table.add_column("Share", justify="right")

    for step, seconds in sorted(stats.step_mean_seconds.items(), key=lambda kv: -kv[1]):
        table.add_row(step, f"{seconds:.0f}", f"{seconds / total:.0%}")

    console.print(table)
    console.print(
        f"Wall clock is {stats.mean_seconds:.0f}s per page - less than these add up to,"
        " because the phases run several pages at once.",
    )


def print_failures(ledger: Ledger) -> None:
    """Print the pages whose most recent attempt failed, and where they failed.

    Args:
        ledger: The parsed ledger.

    """
    failures = [record for record in ledger.latest_by_page().values() if not record.is_ok]

    console = Console()
    if not failures:
        console.print("No failed pages recorded.")
        return

    table = Table(title=f"{len(failures)} failed page(s)")
    table.add_column("Vol", justify="right")
    table.add_column("Title")
    table.add_column("Page")
    table.add_column("Failed at")
    table.add_column("When")

    for record in sorted(failures, key=lambda r: (r.volume, r.title, r.page)):
        table.add_row(
            str(record.volume),
            record.title,
            record.page,
            record.failed_step or "unknown",
            record.finished,
        )

    console.print(table)


def print_json(
    statuses: list[VolumeStatus], seconds_per_page: float, current_recipe_id: str
) -> None:
    """Print the report as json, for scripting.

    Args:
        statuses: The volumes to report on.
        seconds_per_page: Measured cost of a page, or 0 when nothing has been measured.
        current_recipe_id: The id of the recipe the pipeline would use now.

    """
    report = {
        "recipe_id": current_recipe_id,
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


@app.command(help="Report what the restore pipeline has done and what is left")
def main(  # noqa: PLR0913
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    log_level_str: LogLevelArg = "WARNING",
    ledger_file: Annotated[
        Path | None,
        typer.Option("--ledger", help="The ledger to take timings and failures from."),
    ] = None,
    failed: bool = typer.Option(
        default=False,
        help="List the pages whose last attempt failed, instead of the volume summary.",
    ),
    steps: bool = typer.Option(
        default=False,
        help="Show where the time goes per pipeline step, instead of the volume summary.",
    ),
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the summary as json."),
    ] = False,
) -> None:
    init_logging(APP_LOGGING_NAME, "restore-status.log", log_level_str)

    ledger = read_ledger(ledger_file or get_default_ledger_file())

    if failed:
        print_failures(ledger)
        return

    recipe = get_current_recipe(SCALE, do_palette_snap=True)
    logger.info(f"Current recipe {recipe.recipe_id}: {recipe.as_json()}")

    if steps:
        print_step_breakdown(ledger, recipe.recipe_id)
        return

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    statuses = get_status_by_volume(comics_database, titles, recipe.recipe_id)
    seconds_per_page = _get_seconds_per_page(ledger, recipe.recipe_id)

    if as_json:
        print_json(statuses, seconds_per_page, recipe.recipe_id)
        return

    print_status_table(statuses, seconds_per_page, recipe.recipe_id)


if __name__ == "__main__":
    app()
