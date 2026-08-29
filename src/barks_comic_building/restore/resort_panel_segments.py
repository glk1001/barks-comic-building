"""Re-order existing panel segments files into our reading order, without re-running kumiko.

`barks-batch-panel-bounds` sorts the panels it gets from kumiko before saving. Files made
before that existed hold kumiko's order, which reads jogged tiers column-wise. The panel
index is the public panel number, so those files are silently mis-numbered until they are
re-sorted - and once re-sorted, everything that named a panel on that page (the censorship
CSV, the OCR groups, the search index) must be re-pointed. So this is a one-off migration
tool with a dry run that lists exactly which pages would change.
"""

import json
from pathlib import Path
from typing import Any

import typer
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.comics_utils import get_abbrev_path
from comic_utils.comic_consts import JPG_FILE_EXT, OVERALL_BOUNDS_ONLY_SUFFIX
from comic_utils.common_typer_options import LogLevelArg, TitleArg, VolumesArg
from comic_utils.panel_bounding_box_processor import BoundingBoxProcessor
from comic_utils.panel_segmentation import (
    apply_panel_order_override,
    get_min_max_panel_values,
    sort_panels_in_reading_order,
)
from loguru import logger

from barks_comic_building.cli_setup import get_comic_titles, init_logging

APP_LOGGING_NAME = "rsrt"


def get_resorted_segment_info(
    segment_info: dict[str, Any], override_dir: Path, segments_file: Path
) -> tuple[dict[str, Any], list[int]] | None:
    """Return the segments in reading order and the new order, or None if already in order.

    Args:
        segment_info: The parsed segments json.
        override_dir: The page's "bounded" fixes dir, holding any order or bounds override.
        segments_file: The segments json - its stem names the overrides.

    Returns:
        ``(new segment info, order)`` where ``order[i]`` is the old 1-based number of the
        panel now at position ``i``; or None when nothing would move.

    """
    panels = [list(p) for p in segment_info["panels"]]
    sorted_panels = sort_panels_in_reading_order(panels)
    order_override = BoundingBoxProcessor.get_panel_order_override(override_dir, segments_file)
    if order_override is not None:
        sorted_panels = apply_panel_order_override(sorted_panels, order_override)

    if sorted_panels == panels:
        return None

    new_info = {**segment_info, "panels": sorted_panels}

    overall_bounds_override = override_dir / (
        segments_file.stem + OVERALL_BOUNDS_ONLY_SUFFIX + JPG_FILE_EXT
    )
    if not overall_bounds_override.is_file():
        new_info["overall_bounds"] = list(get_min_max_panel_values(new_info))

    return new_info, [panels.index(p) + 1 for p in sorted_panels]


def resort_segments_file(segments_file: Path, override_dir: Path, *, dry_run: bool) -> bool:
    """Re-sort one segments file in place. Returns whether its order changed (or would).

    Args:
        segments_file: The segments json.
        override_dir: The page's "bounded" fixes dir.
        dry_run: Report only; leave the file alone.

    Returns:
        True when the panel order differed from reading order.

    """
    if segments_file.is_symlink():
        logger.info(f'Linked from another volume - skipping "{get_abbrev_path(segments_file)}".')
        return False
    if not segments_file.is_file():
        logger.warning(f'No segments file "{get_abbrev_path(segments_file)}" - skipping.')
        return False

    with segments_file.open() as f:
        segment_info = json.load(f)

    resorted = get_resorted_segment_info(segment_info, override_dir, segments_file)
    if resorted is None:
        return False

    new_info, order = resorted
    verb = "Would re-order" if dry_run else "Re-ordered"
    logger.warning(f'{verb} "{get_abbrev_path(segments_file)}": new order {order}.')

    if not dry_run:
        BoundingBoxProcessor.save_panels_segment_info(segments_file, new_info)

    return True


def resort_panel_segments(
    comics_database: ComicsDatabase, title_list: list[str], *, dry_run: bool
) -> int:
    """Re-sort every restorable page's segments file for each title.

    Args:
        comics_database: The comics database.
        title_list: The titles to process.
        dry_run: Report only.

    Returns:
        The number of pages whose order changed (or would).

    """
    num_changed = 0
    for title in title_list:
        logger.info(f'Checking panel order for all pages in "{title}"...')
        comic = comics_database.get_comic_book(title)
        override_dir = comic.get_srce_original_fixes_bounded_dir()

        for segments_file in comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES):
            if resort_segments_file(segments_file, override_dir, dry_run=dry_run):
                num_changed += 1

    verb = "would change" if dry_run else "changed"
    logger.info(f"Panel order {verb} on {num_changed} pages.")
    return num_changed


app = typer.Typer()


@app.command(help="Re-order existing panel segments files into reading order (no kumiko run)")
def main(
    volumes_str: VolumesArg = "",
    title_str: TitleArg = "",
    dry_run: bool = typer.Option(
        default=False, help="List the pages whose panel order would change; write nothing."
    ),
    log_level_str: LogLevelArg = "INFO",
) -> None:
    init_logging(APP_LOGGING_NAME, "resort-panel-segments.log", log_level_str)

    comics_database, titles = get_comic_titles(volumes_str, title_str)

    resort_panel_segments(comics_database, titles, dry_run=dry_run)


if __name__ == "__main__":
    app()
