"""Stage cover artifacts as FANTA_02 "extra" pages for the build pipeline.

The synthetic "All Covers" collection is a FANTA_02 comic whose pages are numbered
from ``COVER_COLLECTION_PAGE_BASE`` (see
``barks_covers.get_cover_collection_pages``). Each located cover's real files live
in its own volume's back-matter cover gallery (``COVER_LOCATIONS``). This symlinks
them into the matching FANTA_02 dirs as page ``base + i`` so the existing pipeline
processes ``All Covers`` like any other title - and reuses whatever work is
already done.

Covers are ``PageType.COVER``: they are built full-page (scaled with black bars,
never cropped to panels or restored), so only two source files are worth staging
(each linked only when it exists):

* the original scan   -> FANTA_02 *fixes* dir      (``.jpg``)
* the upscayled image -> FANTA_02 upscayled dir    (``.png``)

The original scan is linked into FANTA_02's *fixes* dir (read-write) rather than
its read-only original dir, so no permission changes are needed. There is no
restore or panel-bounds stage for covers - a COVER page never reads a restored,
restored-svg, or panel-segments file.

The staged fixes images also double as the verification of the extrapolated
``COVER_LOCATIONS`` page numbers: every staged image should visibly be a cover. A
wrong run of images from one source volume means that volume's gallery page offset
is off - fix its ``COVER_LOCATIONS`` entries, restage, and drop their
"extrapolated - verify" comments.

Usage::

    barks-stage-covers
    barks-stage-covers --copy                     # copy instead of symlink
    barks-batch-upscayl --title "All Covers"      # only if some are unprocessed
    barks-build         --title "All Covers"      # -> All Covers.cbz
    barks-stage-covers --remove                   # clean up
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import typer
from barks_fantagraphics.barks_covers import (
    COVER_COLLECTION_PAGE_BASE,
    get_cover_location,
    get_located_covers,
)
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comic_book_info import COVER_COLLECTION_VOLUME
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.comic_consts import JPG_FILE_EXT, PNG_FILE_EXT
from comic_utils.common_typer_options import LogLevelArg  # noqa: TC002
from loguru import logger

from barks_comic_building.cli_setup import init_logging

if TYPE_CHECKING:
    from pathlib import Path

APP_LOGGING_NAME = "cvrs"

# Nominal volume the collection is built as (matches All Covers.ini's source_comic).
COLLECTION_VOLUME = COVER_COLLECTION_VOLUME


def _cover_candidate_links(
    comics_database: ComicsDatabase, volume: int, page: int, collection_page: int
) -> list[tuple[Path, Path]]:
    """Return all ``(link, source)`` candidates for one located cover.

    Each pair maps a FANTA_02 page-``collection_page`` slot to the cover's
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
    # ... linked into FANTA_02's read-write *fixes* dir (not its read-only original dir).
    candidates = [
        (
            comics_database.get_fantagraphics_fixes_volume_image_dir(COLLECTION_VOLUME)
            / (dst + JPG_FILE_EXT),
            original_source,
        ),
    ]

    # Covers are PageType.COVER: they are built full-page from the upscayled scan
    # (or the original), never restored or panel-processed, so only the upscayled
    # image is worth staging alongside the original.
    upscayled_source_dir = comics_database.get_fantagraphics_upscayled_volume_image_dir(volume)
    upscayled_dest_dir = comics_database.get_fantagraphics_upscayled_volume_image_dir(
        COLLECTION_VOLUME
    )
    candidates.append(
        (upscayled_dest_dir / (dst + PNG_FILE_EXT), upscayled_source_dir / (src + PNG_FILE_EXT))
    )

    return candidates


def get_staged_links(comics_database: ComicsDatabase) -> list[tuple[Path, Path]]:
    """Return every ``(link, source)`` candidate across all located covers.

    Order follows ``get_located_covers()`` so the ``base + i`` numbering matches
    the collection ``ComicBook`` and the reader's override.
    """
    links: list[tuple[Path, Path]] = []
    for i, cover in enumerate(get_located_covers()):
        location = get_cover_location(cover)
        assert location is not None  # located by construction
        volume, page = location
        collection_page = COVER_COLLECTION_PAGE_BASE + i
        links.extend(_cover_candidate_links(comics_database, volume, page, collection_page))
    return links


def stage(comics_database: ComicsDatabase, *, remove: bool, copy: bool) -> None:
    """Create (or with ``remove``, delete) the FANTA_02 cover links.

    On create, a link is made only when its source file exists (so already-built
    artifacts are reused and missing ones are simply left for the pipeline); with
    ``copy``, files are copied instead of symlinked. On remove, any existing
    staged file is deleted regardless of its source or whether it was a symlink.
    """
    candidates = get_staged_links(comics_database)
    if not candidates:
        logger.warning("No located covers (COVER_LOCATIONS is empty). Nothing to do.")
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
        if copy:
            shutil.copy2(source, link)
        else:
            link.symlink_to(source)
        count += 1
        logger.info(f'Staged "{link}" -> "{source}".')

    logger.info(f"{'Removed' if remove else 'Staged'} {count} cover links.")


app = typer.Typer()


@app.command(help="Symlink cover artifacts as FANTA_02 extras to build the All Covers collection.")
def main(
    log_level_str: LogLevelArg = "INFO",
    *,
    remove: bool = typer.Option(
        default=False, help="Remove the staged links instead of creating them."
    ),
    copy: bool = typer.Option(default=False, help="Copy files instead of symlinking them."),
) -> None:
    if remove and copy:
        msg = "Options --remove and --copy cannot be combined."
        raise typer.BadParameter(msg)
    init_logging(APP_LOGGING_NAME, "stage-covers.log", log_level_str)
    comics_database = ComicsDatabase(for_building_comics=True)
    stage(comics_database, remove=remove, copy=copy)


if __name__ == "__main__":
    app()
