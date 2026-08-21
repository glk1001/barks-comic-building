"""Stage one-pager artifacts as FANTA_01 "extra" pages for the build pipeline.

The synthetic "All One-Pagers" collection is a FANTA_01 comic whose body pages are
numbered from ``ONE_PAGER_COLLECTION_PAGE_BASE`` (see
``comic_book_info.get_one_pager_collection_pages``). Each one-pager's real files live
in its own volume (``ONE_PAGER_LOCATIONS``). This symlinks them into the matching
FANTA_01 dirs as page ``base + i`` so the existing pipeline processes ``All
One-Pagers`` like any other title - and reuses whatever work is already done.

For each located one-pager it links (only when the source file exists):

* the original scan       -> FANTA_01 *fixes* dir          (``.jpg`` or ``.png``)
* the upscayled image     -> FANTA_01 upscayled dir        (``.png``)
* the restored image      -> FANTA_01 restored dir         (``.png``)
* the restored-svg files  -> FANTA_01 restored-svg dir     (``.svg`` + ``.svg.png``)
* the panel-segments      -> FANTA_01 panel-segments dir   (``.json``)

The first two are taken from the source volume's *fixes* tree when that volume has a
fix for the page, and from its plain tree otherwise - the build's own precedence; see
`collection_sources` for what preferring the plain tree instead silently produced. The
original scan keeps whichever extension its source has.

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
    ONE_PAGER_COLLECTION_VOLUME,
    ONE_PAGER_LOCATIONS,
    get_located_one_pagers,
)
from barks_fantagraphics.comics_database import ComicsDatabase
from comic_utils.comic_consts import JSON_FILE_EXT, PNG_FILE_EXT, SVG_FILE_EXT
from comic_utils.common_typer_options import LogLevelArg  # noqa: TC002
from loguru import logger

from barks_comic_building.build import collection_staging
from barks_comic_building.cli_setup import init_logging

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.barks_titles import Titles

    from barks_comic_building.build.collection_staging import Member

APP_LOGGING_NAME = "1pgr"

# Nominal volume the collection is built as (matches All One-Pagers.ini's source_comic).
COLLECTION_VOLUME = ONE_PAGER_COLLECTION_VOLUME

# What `stage` calls one member, and what it says when the table yields none.
_NOUN = "one-pager"
_NOTHING_TO_DO = "No located one-pagers (ONE_PAGER_LOCATIONS is all _TODO). Nothing to do."


def _located_members() -> list[Member]:
    """Return the located one-pagers as ``(title, volume, page)``, in table order.

    The table's third field is the page in the original issue, which staging has no use
    for - the collection is assembled out of the Fantagraphics volumes.
    """
    members: list[Member] = []
    for title in get_located_one_pagers():
        volume, page, _issue_page = ONE_PAGER_LOCATIONS[title]
        members.append((title, volume, page))

    return members


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

    # The scan and its upscayl each have a fixes tree beside them, and so a precedence
    # to honour; `collection_staging` names the source and the slot for both.
    candidates = [
        collection_staging.original_scan_candidate(
            comics_database, COLLECTION_VOLUME, volume, src, dst
        ),
        collection_staging.upscayled_candidate(
            comics_database, COLLECTION_VOLUME, volume, src, dst
        ),
    ]

    # The remaining built artifacts: (per-volume source dir, FANTA_01 dest dir, suffixes).
    # No fixes tree exists beside any of these - a restore or a segments file is derived
    # from the scan chosen above rather than hand-edited in place.
    artifact_dirs: list[tuple[Path, Path, list[str]]] = [
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


def get_staged_links_by_title(
    comics_database: ComicsDatabase,
) -> dict[Titles, list[tuple[Path, Path]]]:
    """Return each located one-pager's ``(link, source)`` candidates, keyed by title.

    Order follows ``get_located_one_pagers()`` so the ``base + i`` numbering matches
    the collection ``ComicBook`` and the reader's override. Exposed per title so a
    status report can grade one one-pager's staging against the same rules this
    module stages by, rather than restating them.
    """

    def candidate_links(volume: int, page: int, collection_page: int) -> list[tuple[Path, Path]]:
        return _one_pager_candidate_links(comics_database, volume, page, collection_page)

    return collection_staging.staged_links_by_title(
        _located_members(), ONE_PAGER_COLLECTION_PAGE_BASE, candidate_links
    )


def get_staged_links(comics_database: ComicsDatabase) -> list[tuple[Path, Path]]:
    """Return every ``(link, source)`` candidate across all located one-pagers.

    Order follows ``get_located_one_pagers()`` so the ``base + i`` numbering matches
    the collection ``ComicBook`` and the reader's override.
    """
    return collection_staging.flatten(get_staged_links_by_title(comics_database))


def missing_volume_dirs(comics_database: ComicsDatabase) -> list[tuple[int, Path]]:
    """Return the ``(volume, image dir)`` pairs a located one-pager needs but that are absent.

    Guards the failure that is otherwise silent: a volume's directory name comes from its
    ``VOLUME_nn`` constant, so a single wrong word there makes every source path for that
    volume miss. `stage` skips any candidate whose source is not a file, so a misnamed
    volume stages nothing at all and reports success - the only symptom being a link count
    lower than expected.

    Args:
        comics_database: The database supplying the volume directory paths.

    Returns:
        One pair per offending volume, ordered by volume number; empty when all are present.

    """
    return collection_staging.missing_volume_dirs(comics_database, _located_members())


def stage(comics_database: ComicsDatabase, *, remove: bool) -> None:
    """Create (or with ``remove``, delete) the FANTA_01 one-pager symlinks.

    See `collection_staging.stage` for the create and remove rules, which both
    collections share. There is no ``--copy`` here: unlike the covers collection, this
    one is not staged onto filesystems that cannot hold the links.
    """
    collection_staging.stage(
        get_staged_links(comics_database),
        remove=remove,
        copy=False,
        noun=_NOUN,
        nothing_to_do=_NOTHING_TO_DO,
    )


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

    # Checked here rather than in `stage` because it is a precondition of staging, not of
    # working out the links: `--remove` must still clean up after a volume goes missing.
    if not remove:
        missing = missing_volume_dirs(comics_database)
        if missing:
            for volume, image_dir in missing:
                logger.error(f'Volume {volume} original image dir not found: "{image_dir}".')
            logger.error(
                "A located one-pager points at a volume that is not on disk, so it would"
                " stage nothing and report success. Check each volume's VOLUME_nn constant"
                " in fanta_comics_info.py names its actual directory in the"
                f' "{comics_database.get_fantagraphics_original_root_dir()}" tree.'
            )
            raise typer.Exit(1)

    stage(comics_database, remove=remove)


if __name__ == "__main__":
    app()
