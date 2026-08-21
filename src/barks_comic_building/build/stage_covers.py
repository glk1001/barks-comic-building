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

* the original scan   -> FANTA_02 *fixes* dir      (``.jpg`` or ``.png``)
* the upscayled image -> FANTA_02 upscayled dir    (``.png``)

Each is taken from the source volume's *fixes* tree when that volume has a fix for
the page, and from its plain tree otherwise - the build's own precedence, and not
obvious enough to leave implicit here; see `collection_sources` for what preferring
the original instead silently produced. The original scan keeps whichever extension
its source has, so a ``.png`` fix is not staged under a ``.jpg`` name.

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

from typing import TYPE_CHECKING

import typer
from barks_fantagraphics.barks_covers import (
    COVER_COLLECTION_PAGE_BASE,
    get_cover_location,
    get_cover_title,
    get_located_covers,
)
from barks_fantagraphics.comic_book import get_page_str
from barks_fantagraphics.comic_book_info import COVER_COLLECTION_VOLUME
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.common_typer_options import LogLevelArg  # noqa: TC002
from loguru import logger

from barks_comic_building.build import collection_staging
from barks_comic_building.cli_setup import init_logging

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.barks_titles import Titles

    from barks_comic_building.build.collection_staging import Member

APP_LOGGING_NAME = "cvrs"

# Nominal volume the collection is built as (matches All Covers.ini's source_comic).
COLLECTION_VOLUME = COVER_COLLECTION_VOLUME

# What `stage` calls one member, and what it says when the table yields none.
_NOUN = "cover"
_NOTHING_TO_DO = "No located covers (COVER_LOCATIONS is empty). Nothing to do."


def _located_members() -> list[Member]:
    """Return the located covers as ``(title, volume, page)``, in table order.

    `get_cover_location` is typed optional because `COVER_LOCATIONS` allows a cover with
    no location yet, but `get_located_covers` has already filtered those out. Narrowing
    at this one point of production - rather than asserting it again at each use - is
    what lets the rest of this module and the shared engine work in plain tuples.

    Raises:
        RuntimeError: If a cover `get_located_covers` returned has no location after
            all, which is a contradiction inside `barks_covers` rather than a cover
            still waiting to be placed.

    """
    members: list[Member] = []
    for cover in get_located_covers():
        location = get_cover_location(cover)
        title = get_cover_title(cover)
        if location is None:
            msg = f'Located cover "{title}" has no location.'
            raise RuntimeError(msg)
        volume, page = location
        members.append((title, volume, page))

    return members


def _cover_candidate_links(
    comics_database: ComicsDatabase, volume: int, page: int, collection_page: int
) -> list[tuple[Path, Path]]:
    """Return all ``(link, source)`` candidates for one located cover.

    Each pair maps a FANTA_02 page-``collection_page`` slot to the cover's
    page-``page`` file in ``volume``. Covers are PageType.COVER: they are built
    full-page from the upscayled scan (or the original), never restored or
    panel-processed, so those two are the only artifacts worth staging. Not filtered by
    existence - the caller decides (create only existing sources; remove any link).
    """
    src = get_page_str(page)
    dst = get_page_str(collection_page)

    return [
        collection_staging.original_scan_candidate(
            comics_database, COLLECTION_VOLUME, volume, src, dst
        ),
        collection_staging.upscayled_candidate(
            comics_database, COLLECTION_VOLUME, volume, src, dst
        ),
    ]


def get_staged_links_by_title(
    comics_database: ComicsDatabase,
) -> dict[Titles, list[tuple[Path, Path]]]:
    """Return each located cover's ``(link, source)`` candidates, keyed by cover title.

    Order follows ``get_located_covers()`` so the ``base + i`` numbering matches the
    collection ``ComicBook`` and the reader's override. Exposed per title so a status
    report can grade one cover's staging against the same rules this module stages
    by, rather than restating them.
    """

    def candidate_links(volume: int, page: int, collection_page: int) -> list[tuple[Path, Path]]:
        return _cover_candidate_links(comics_database, volume, page, collection_page)

    return collection_staging.staged_links_by_title(
        _located_members(), COVER_COLLECTION_PAGE_BASE, candidate_links
    )


def get_staged_links(comics_database: ComicsDatabase) -> list[tuple[Path, Path]]:
    """Return every ``(link, source)`` candidate across all located covers.

    Order follows ``get_located_covers()`` so the ``base + i`` numbering matches
    the collection ``ComicBook`` and the reader's override.
    """
    return collection_staging.flatten(get_staged_links_by_title(comics_database))


def missing_volume_dirs(comics_database: ComicsDatabase) -> list[tuple[int, Path]]:
    """Return the ``(volume, image dir)`` pairs a located cover needs but that are absent.

    Guards the failure that is otherwise silent: a volume's directory name comes from its
    ``VOLUME_nn`` constant, so a single wrong word there makes every source path for that
    volume miss. `stage` skips any candidate whose source is not a file, which is worse
    here than a plain no-op - a cover added to the middle of the date-ordered table shifts
    every later cover's collection page, so the restage that follows moves all the
    reachable covers to their new pages and leaves the unreachable ones still attached to
    their *previous* occupants. Those pages then build as valid images of the wrong cover.

    Args:
        comics_database: The database supplying the volume directory paths.

    Returns:
        One pair per offending volume, ordered by volume number; empty when all are present.

    """
    return collection_staging.missing_volume_dirs(comics_database, _located_members())


def stage(comics_database: ComicsDatabase, *, remove: bool, copy: bool) -> None:
    """Create (or with ``remove``, delete) the FANTA_02 cover links.

    See `collection_staging.stage` for the create, remove and copy rules, which both
    collections share.
    """
    collection_staging.stage(
        get_staged_links(comics_database),
        remove=remove,
        copy=copy,
        noun=_NOUN,
        nothing_to_do=_NOTHING_TO_DO,
    )


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

    # Checked here rather than in `stage` because it is a precondition of staging, not of
    # working out the links: `--remove` must still clean up after a volume goes missing.
    if not remove:
        missing = missing_volume_dirs(comics_database)
        if missing:
            for volume, image_dir in missing:
                logger.error(f'Volume {volume} original image dir not found: "{image_dir}".')
            logger.error(
                "A located cover points at a volume that is not on disk. Restaging now"
                " would leave its pages attached to whichever covers held those page"
                " numbers before. Check each volume's VOLUME_nn constant in"
                " fanta_comics_info.py names its actual directory in the"
                f' "{comics_database.get_fantagraphics_original_root_dir()}" tree.'
            )
            raise typer.Exit(1)

    stage(comics_database, remove=remove, copy=copy)


if __name__ == "__main__":
    app()
