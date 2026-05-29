"""Stage one-pager artifacts as FANTA_01 "extra" pages for the build pipeline.

The synthetic "All One-Pagers" collection is a FANTA_01 comic whose body pages are
numbered from ``ONE_PAGER_COLLECTION_PAGE_BASE`` (see
``comic_book_info.get_one_pager_collection_pages``). Each one-pager's real files live
in its own volume (``ONE_PAGER_LOCATIONS``). This symlinks them into the matching
FANTA_01 dirs as page ``base + i`` so the existing pipeline processes ``All
One-Pagers`` like any other title - and reuses whatever work is already done.

For each located one-pager it links (only when the source file exists):

* the original scan       -> FANTA_01 *fixes* dir          (``.jpg``)
* the upscayled image     -> FANTA_01 upscayled dir        (``.png``)
* the restored image      -> FANTA_01 restored dir         (``.png``)
* the restored-svg files  -> FANTA_01 restored-svg dir     (``.svg`` + ``.svg.png``)
* the panel-segments      -> FANTA_01 panel-segments dir   (``.json``)

Many one-pagers are already processed (their pages were built as part of other
work), so most of these already exist and are simply reused; only genuinely missing
stages get recomputed. The original scan is linked into FANTA_01's *fixes* dir
(read-write) rather than its read-only original dir, so no permission changes are
needed. All of these target dirs are normal read-write build dirs.

Usage::

    barks-stage-one-pagers
    barks-batch-upscayl      --title "All One-Pagers"   # only if some are unprocessed
    barks-batch-restore      --title "All One-Pagers" --work-dir <dir>
    barks-batch-panel-bounds --title "All One-Pagers"
    barks-build              --title "All One-Pagers"   # -> All One-Pagers.cbz
    barks-stage-one-pagers --remove                     # clean up
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comic_book_info import (
    ONE_PAGER_COLLECTION_PAGE_BASE,
    ONE_PAGER_LOCATIONS,
    get_located_one_pagers,
)
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.comic_consts import JPG_FILE_EXT, JSON_FILE_EXT, PNG_FILE_EXT, SVG_FILE_EXT
from comic_utils.common_typer_options import LogLevelArg  # noqa: TC002
from loguru import logger

from barks_comic_building.cli_setup import init_logging

if TYPE_CHECKING:
    from pathlib import Path

APP_LOGGING_NAME = "1pgr"

# Nominal volume the collection is built as (matches All One-Pagers.ini's source_comic).
COLLECTION_VOLUME = 1


def _one_pager_candidate_links(
    comics_database: ComicsDatabase, volume: int, page: int, collection_page: int
) -> list[tuple[Path, Path]]:
    """Return all ``(link, source)`` candidates for one located one-pager.

    Each pair maps a FANTA_01 page-``collection_page`` slot to the one-pager's
    page-``page`` file in ``volume``, across every artifact dir. Not filtered by
    existence - the caller decides (create only existing sources; remove any link).
    """
    src = get_page_str(page)
    dst = get_page_str(collection_page)

    # The original scan: prefer the volume's original dir, fall back to its fixes dir.
    original_source = comics_database.get_fantagraphics_volume_image_dir(volume) / (
        src + JPG_FILE_EXT
    )
    if not original_source.is_file():
        original_source = comics_database.get_fantagraphics_fixes_volume_image_dir(volume) / (
            src + JPG_FILE_EXT
        )
    # ... linked into FANTA_01's read-write *fixes* dir (not its read-only original dir).
    candidates = [
        (
            comics_database.get_fantagraphics_fixes_volume_image_dir(COLLECTION_VOLUME)
            / (dst + JPG_FILE_EXT),
            original_source,
        ),
    ]

    # The already-built artifacts: (per-volume source dir, FANTA_01 dest dir, suffixes).
    artifact_dirs: list[tuple[Path, Path, list[str]]] = [
        (
            comics_database.get_fantagraphics_upscayled_volume_image_dir(volume),
            comics_database.get_fantagraphics_upscayled_volume_image_dir(COLLECTION_VOLUME),
            [PNG_FILE_EXT],
        ),
        (
            comics_database.get_fantagraphics_restored_volume_image_dir(volume),
            comics_database.get_fantagraphics_restored_volume_image_dir(COLLECTION_VOLUME),
            [PNG_FILE_EXT],
        ),
        (
            comics_database.get_fantagraphics_restored_svg_volume_image_dir(volume),
            comics_database.get_fantagraphics_restored_svg_volume_image_dir(COLLECTION_VOLUME),
            [SVG_FILE_EXT, SVG_FILE_EXT + PNG_FILE_EXT],
        ),
        (
            comics_database.get_fantagraphics_panel_segments_volume_dir(volume),
            comics_database.get_fantagraphics_panel_segments_volume_dir(COLLECTION_VOLUME),
            [JSON_FILE_EXT],
        ),
    ]
    for source_dir, dest_dir, suffixes in artifact_dirs:
        candidates.extend(
            (dest_dir / (dst + suffix), source_dir / (src + suffix)) for suffix in suffixes
        )

    return candidates


def get_staged_links(comics_database: ComicsDatabase) -> list[tuple[Path, Path]]:
    """Return every ``(link, source)`` candidate across all located one-pagers.

    Order follows ``get_located_one_pagers()`` so the ``base + i`` numbering matches
    the collection ``ComicBook`` and the reader's override.
    """
    links: list[tuple[Path, Path]] = []
    for i, title in enumerate(get_located_one_pagers()):
        volume, page, _issue_page = ONE_PAGER_LOCATIONS[title]
        collection_page = ONE_PAGER_COLLECTION_PAGE_BASE + i
        links.extend(_one_pager_candidate_links(comics_database, volume, page, collection_page))
    return links


def stage(comics_database: ComicsDatabase, *, remove: bool) -> None:
    """Create (or with ``remove``, delete) the FANTA_01 one-pager symlinks.

    On create, a link is made only when its source file exists (so already-built
    artifacts are reused and missing ones are simply left for the pipeline). On
    remove, any existing link is deleted regardless of its source.
    """
    candidates = get_staged_links(comics_database)
    if not candidates:
        logger.warning("No located one-pagers (ONE_PAGER_LOCATIONS is all _TODO). Nothing to do.")
        return

    count = 0
    for link, source in candidates:
        if remove:
            if link.is_symlink() or link.exists():
                link.unlink()
                count += 1
                logger.info(f'Removed staged link "{link}".')
            continue

        if not source.is_file():
            continue

        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(source)
        count += 1
        logger.info(f'Staged "{link}" -> "{source}".')

    logger.info(f"{'Removed' if remove else 'Staged'} {count} one-pager links.")


app = typer.Typer()


@app.command(
    help="Symlink one-pager artifacts as FANTA_01 extras to build the All One-Pagers collection."
)
def main(
    log_level_str: LogLevelArg = "INFO",
    *,
    remove: bool = typer.Option(
        default=False, help="Remove the staged links instead of creating them."
    ),
) -> None:
    init_logging(APP_LOGGING_NAME, "stage-one-pagers.log", log_level_str)
    comics_database = ComicsDatabase(for_building_comics=True)
    stage(comics_database, remove=remove)


if __name__ == "__main__":
    app()
