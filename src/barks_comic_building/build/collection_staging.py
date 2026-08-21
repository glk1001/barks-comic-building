"""The staging engine both synthetic collections run on.

"All Covers" and "All One-Pagers" are assembled the same way: walk the collection's
location table in order, give member *i* the collection page ``base + i``, and point
that page's slots at the member's real files in its own volume. Only two things differ -
the table each walks, and which artifacts are worth staging (a cover is built full-page
from two files; a one-pager goes through the whole restore pipeline and has six).

Everything else - the numbering loop, the missing-volume guard, and `stage` itself with
its create, remove and copy rules - was written out twice, once per collection, and the
two copies drifted: only one of them had factored out link creation, only one grew
``--copy``, and the remove-path bug `_remove_staged_slot` fixes was sitting in both. It
lives here now, taking values rather than being subclassed, which leaves each stager
holding just its table and its artifact list.

Which *source* a page is staged from is a separate question and belongs to
`collection_sources`; this module decides nothing about it.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from comic_utils.comic_consts import PNG_FILE_EXT
from loguru import logger

from barks_comic_building.build.collection_sources import (
    original_scan_source,
    staged_link_for,
    superseded_links,
    upscayled_scan_source,
)
from barks_comic_building.build.utils import links_to

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from barks_fantagraphics.barks_titles import Titles
    from barks_fantagraphics.comics_database import ComicsDatabase

# One located collection member: its title, and the volume and page its real files are
# in. Built by each stager from its own location table, in that table's order.
type Member = tuple[Titles, int, int]

# Builds one member's ``(link, source)`` candidates, given its source volume, its page
# in that volume, and the collection page it is staged as.
type CandidateLinks = Callable[[int, int, int], list[tuple[Path, Path]]]


def staged_links_by_title(
    members: Sequence[Member], page_base: int, candidate_links: CandidateLinks
) -> dict[Titles, list[tuple[Path, Path]]]:
    """Return each member's ``(link, source)`` candidates, keyed by title.

    Args:
        members: The located members, in location-table order.
        page_base: The collection page the first member is staged as.
        candidate_links: Builds one member's candidates.

    Returns:
        The candidates per title. Member *i* is staged as page ``page_base + i``, so the
        numbering matches the collection `ComicBook` and the reader's override.

    """
    return {
        title: candidate_links(volume, page, page_base + i)
        for i, (title, volume, page) in enumerate(members)
    }


def flatten(links_by_title: dict[Titles, list[tuple[Path, Path]]]) -> list[tuple[Path, Path]]:
    """Return every ``(link, source)`` candidate across all members, in member order."""
    return [link for links in links_by_title.values() for link in links]


def missing_volume_dirs(
    comics_database: ComicsDatabase, members: Sequence[Member]
) -> list[tuple[int, Path]]:
    """Return the ``(volume, image dir)`` pairs the members need but that are absent.

    Args:
        comics_database: The database supplying the volume directory paths.
        members: The located members whose volumes must be reachable.

    Returns:
        One pair per offending volume, ordered by volume number, however many members
        that volume holds; empty when all are present.

    """
    missing: dict[int, Path] = {}
    for _title, volume, _page in members:
        image_dir = comics_database.get_fantagraphics_volume_image_dir(volume)
        if not image_dir.is_dir():
            missing[volume] = image_dir

    return sorted(missing.items())


def original_scan_candidate(
    comics_database: ComicsDatabase, collection_volume: int, volume: int, src: str, dst: str
) -> tuple[Path, Path]:
    """Return the ``(link, source)`` pair for a collection page's original-scan slot.

    The source is the volume's fixes file when it has one and its original otherwise -
    the build's own precedence, see `collection_sources`. The link goes into the
    collection's read-write *fixes* dir rather than its read-only original dir, so no
    permission changes are needed to stage, and takes the source's own extension.

    Args:
        comics_database: The database supplying the volume directory paths.
        collection_volume: The volume the collection is built as.
        volume: The Fantagraphics volume the page is taken from.
        src: The page number in that volume, zero-padded.
        dst: The collection page number, zero-padded.

    Returns:
        The staged slot and the file to stage into it.

    """
    source = original_scan_source(comics_database, volume, src)
    dest_dir = comics_database.get_fantagraphics_fixes_volume_image_dir(collection_volume)

    return staged_link_for(dest_dir, dst, source), source


def upscayled_candidate(
    comics_database: ComicsDatabase, collection_volume: int, volume: int, src: str, dst: str
) -> tuple[Path, Path]:
    """Return the ``(link, source)`` pair for a collection page's upscayled slot.

    The upscayl has a fixes tree of its own, and so the same precedence again. Always a
    ``.png``, at both ends.

    Args:
        comics_database: The database supplying the volume directory paths.
        collection_volume: The volume the collection is built as.
        volume: The Fantagraphics volume the page is taken from.
        src: The page number in that volume, zero-padded.
        dst: The collection page number, zero-padded.

    Returns:
        The staged slot and the file to stage into it.

    """
    source = upscayled_scan_source(comics_database, volume, src)
    dest_dir = comics_database.get_fantagraphics_upscayled_volume_image_dir(collection_volume)

    return dest_dir / (dst + PNG_FILE_EXT), source


def _create_staged_file(link: Path, source: Path, *, copy: bool) -> None:
    """Point ``link`` at ``source``, replacing whatever occupied that page's slot.

    Any slot this one supersedes goes first - see `superseded_links` for why a stale
    sibling is worse than untidy.
    """
    link.parent.mkdir(parents=True, exist_ok=True)
    for superseded in superseded_links(link):
        superseded.unlink()
        logger.info(f'Removed superseded staged slot "{superseded}".')
    if link.is_symlink() or link.exists():
        link.unlink()
    if copy:
        shutil.copy2(source, link)
    else:
        link.symlink_to(source)


def _remove_staged_slot(link: Path) -> int:
    """Delete this page's staged slot, in whichever extension it was staged under.

    Not just ``link``: the slot is named after the source it was staged from, so a page
    staged while its fix was a ``.png`` occupies ``NNN.png``, and once that fix is
    reverted the recomputed link is ``NNN.jpg``. Removing only that leaves the ``.png``
    behind as a dangling symlink in a dir the build probes by both extensions, and
    reports success. The create path already clears the same siblings.

    Args:
        link: The slot the current source names.

    Returns:
        How many files were removed; usually one, or zero if nothing was staged.

    """
    removed = 0
    for path in [link, *superseded_links(link)]:
        if path.is_symlink() or path.exists():
            path.unlink()
            removed += 1
            logger.info(f'Removed staged link "{path}".')

    return removed


def stage(
    candidates: Sequence[tuple[Path, Path]],
    *,
    remove: bool,
    copy: bool,
    noun: str,
    nothing_to_do: str,
) -> None:
    """Create (or with ``remove``, delete) a collection's staged links.

    On create, a link is made only when its source file exists (so already-built
    artifacts are reused and missing ones are simply left for the pipeline), and only
    when it is not already pointing where it should - see `links_to`; with ``copy``,
    files are copied instead of symlinked. On remove, any existing staged file is
    deleted regardless of its source or whether it was a symlink.

    Args:
        candidates: Every ``(link, source)`` pair the collection could stage.
        remove: Delete the staged files instead of creating them.
        copy: Copy the sources instead of symlinking them.
        noun: What one member is called, for the closing count.
        nothing_to_do: Warning to log when the location table yields no members.

    """
    if not candidates:
        logger.warning(nothing_to_do)
        return

    count = 0
    unchanged = 0
    for link, source in candidates:
        if remove:
            count += _remove_staged_slot(link)
            continue

        if not source.is_file():
            continue

        # Only for symlinks: `--copy` asked for a file, so an existing link is not what
        # was asked for however well it points, and `copy2` carries the source's mtime
        # over anyway, which leaves a re-copy idempotent as far as staleness goes.
        if not copy and links_to(link, source):
            unchanged += 1
            logger.debug(f'Already staged - leaving alone: "{link}".')
            continue

        _create_staged_file(link, source, copy=copy)
        count += 1
        logger.info(f'Staged "{link}" -> "{source}".')

    logger.info(f"{'Removed' if remove else 'Staged'} {count} {noun} links.")
    if unchanged:
        logger.info(f"Left {unchanged} already-correct links untouched.")
