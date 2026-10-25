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

import filecmp
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


def members_by_collection_page(members: Sequence[Member], page_base: int) -> dict[int, Member]:
    """Return the members keyed by the collection page each is staged as.

    The one place the numbering is written down: member *i* is staged as page
    ``page_base + i``, which matches the collection `ComicBook` and the reader's
    override. Staging and the integrity check both read it from here, so a page the
    check grades is the page the stager filled.

    Args:
        members: The located members, in location-table order.
        page_base: The collection page the first member is staged as.

    Returns:
        Each member, keyed by its collection page, in location-table order.

    """
    return {page_base + i: member for i, member in enumerate(members)}


def staged_links_by_title(
    members: Sequence[Member], page_base: int, candidate_links: CandidateLinks
) -> dict[Titles, list[tuple[Path, Path]]]:
    """Return each member's ``(link, source)`` candidates, keyed by title.

    Args:
        members: The located members, in location-table order.
        page_base: The collection page the first member is staged as.
        candidate_links: Builds one member's candidates.

    Returns:
        The candidates per title, numbered by `members_by_collection_page`.

    """
    return {
        title: candidate_links(volume, page, collection_page)
        for collection_page, (title, volume, page) in members_by_collection_page(
            members, page_base
        ).items()
    }


def flatten(links_by_title: dict[Titles, list[tuple[Path, Path]]]) -> list[tuple[Path, Path]]:
    """Return every ``(link, source)`` candidate across all members, in member order."""
    return [link for links in links_by_title.values() for link in links]


def original_scan_slot(links: Sequence[tuple[Path, Path]]) -> Path | None:
    """Return the slot a member's original scan is staged into, or None if it has none.

    Positional by design, and the single place that says so: both stagers build their
    candidate list with `original_scan_candidate` first - see `_one_pager_candidate_links`
    and `_cover_candidate_links` - so the scan is ``links[0]``, whatever extension it
    ended up under.

    Identifying it by suffix instead is what this replaces, and it was wrong: the slot
    takes the *source's* extension (see `staged_link_for`), so a member whose volume
    grew a ``.png`` fix is staged as ``NNN.png`` and matched no ``.jpg`` filter. Every
    caller then reported a correctly staged member as having no scan at all, and
    restaging could not clear it. Widening the filter to both extensions is not the fix
    either - the upscayl, restored and svg slots are ``.png`` too.

    Args:
        links: One member's ``(link, source)`` candidates, in stager order.

    Returns:
        The original-scan slot, or None when the member has no candidates.

    """
    if not links:
        return None

    link, _source = links[0]

    return link


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


def _is_staged_copy(path: Path, source: Path) -> bool:
    """Return whether a real file in a slot is a ``--copy`` staging of ``source``.

    `shutil.copy2` keeps the source's size and mtime, which is the signature a shallow
    `filecmp.cmp` compares. Any other real file in a slot is the pipeline's own output -
    a one-pager that belongs to no story is upscayled, restored and segmented in place
    in the collection, and that output has no source to be a copy of.
    """
    return source.is_file() and filecmp.cmp(path, source, shallow=True)


def _resolves_to_slot(source: Path, link: Path) -> bool:
    """Return whether ``source`` resolves to the slot it would be staged into.

    A link in the source volume pointing back at the collection's own file does this.
    Staging it would replace the file with a link to a link to itself - the only copy
    of a restore, gone, and a loop left in its place.
    """
    return source.resolve() == link.parent.resolve() / link.name


def _must_not_stage_over(link: Path, source: Path, *, copy: bool) -> bool:
    """Return whether staging ``source`` into ``link`` must be refused, saying why.

    Refused when the source resolves back to the slot (see `_resolves_to_slot`), and -
    except under ``--copy`` - when the slot holds a real file. ``--copy`` (covers only) is
    an explicit request for real files, and a re-copy after the source changed has to
    replace the old copy, so it keeps replacing.

    Args:
        link: The slot.
        source: The file that would be staged into it.
        copy: Whether the staging copies rather than links.

    Returns:
        True if the slot must be left as it is.

    """
    if _resolves_to_slot(source, link):
        logger.error(f'Not staging "{source}": it resolves back to its own slot "{link}".')
        return True

    if not copy and link.exists() and not link.is_symlink():
        logger.warning(
            f'Not staging "{source}" over "{link}": that is the pipeline\'s own output.'
            " Move it aside by hand if the source should replace it."
        )
        return True

    return False


def _remove_staged_slot(link: Path, source: Path) -> int:
    """Delete this page's staged slot, in whichever extension it was staged under.

    Not just ``link``: the slot is named after the source it was staged from, so a page
    staged while its fix was a ``.png`` occupies ``NNN.png``, and once that fix is
    reverted the recomputed link is ``NNN.jpg``. Removing only that leaves the ``.png``
    behind as a dangling symlink in a dir the build probes by both extensions, and
    reports success. The create path already clears the same siblings.

    Only what staging put there goes: a link, or a ``--copy`` of ``source``. Any other
    real file is the pipeline's own output and is kept - see `_is_staged_copy`.

    Args:
        link: The slot the current source names.
        source: The file the slot is staged from.

    Returns:
        How many files were removed; usually one, or zero if nothing was staged.

    """
    removed = 0
    for path in [link, *superseded_links(link)]:
        if path.is_symlink() or (path.exists() and _is_staged_copy(path, source)):
            path.unlink()
            removed += 1
            logger.info(f'Removed staged link "{path}".')
        elif path.exists():
            logger.warning(f'Kept "{path}": it is the pipeline\'s own output, not a staging.')

    return removed


def _clear_slot_with_no_source(link: Path) -> int:
    """Delete this page's staged links when there is no source to stage into it.

    A slot with no source is not simply "nothing to do". The collection numbers member
    *i* as page ``base + i``, so locating one more member shifts every later page down
    one, and the slot a member inherits already holds the *previous* occupant's links.
    Skipping it leaves those in place: the page then shows the next member's gag, which
    is also correctly staged one page along, so the collection carries it twice. That is
    how `Luncheon Lament` came to share `Come As You Are`'s art - its own volume had no
    upscayl or restore yet, so all five derived slots were passed over and stayed
    pointing at the member that used to sit there.

    Only symlinks go. A real file in one of these slots is the pipeline's own output,
    written in place for a page whose source volume never built it (see
    `superseded_links`), and nothing here staged it or may remove it.

    Args:
        link: The slot whose source is absent.

    Returns:
        How many stale links were removed; usually zero.

    """
    removed = 0
    for path in [link, *superseded_links(link)]:
        if path.is_symlink():
            path.unlink()
            removed += 1
            logger.info(f'Removed stale staged link "{path}" - it has no source.')

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
    files are copied instead of symlinked. A slot whose source does not exist is not
    left as it was but emptied of any *staged* link - see `_clear_slot_with_no_source` for
    the wrong page that leaving it produced. On remove, the staged link or copy is
    deleted, in either extension.

    A real file in a slot is never replaced by a link, nor deleted on remove unless it
    is a ``--copy`` of its source. It is the pipeline's own output for a member whose
    source volume never built it, and often the only copy. Nor is a source staged that
    resolves back to its own slot.

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
    stale = 0
    kept = 0
    for link, source in candidates:
        if remove:
            count += _remove_staged_slot(link, source)
            continue

        if not source.is_file():
            stale += _clear_slot_with_no_source(link)
            continue

        # Only for symlinks: `--copy` asked for a file, so an existing link is not what
        # was asked for however well it points, and `copy2` carries the source's mtime
        # over anyway, which leaves a re-copy idempotent as far as staleness goes.
        if not copy and links_to(link, source):
            unchanged += 1
            logger.debug(f'Already staged - leaving alone: "{link}".')
            continue

        if _must_not_stage_over(link, source, copy=copy):
            kept += 1
            continue

        _create_staged_file(link, source, copy=copy)
        count += 1
        logger.info(f'Staged "{link}" -> "{source}".')

    logger.info(f"{'Removed' if remove else 'Staged'} {count} {noun} links.")
    if unchanged:
        logger.info(f"Left {unchanged} already-correct links untouched.")
    if stale:
        logger.info(f"Removed {stale} stale links whose {noun} has no source to stage.")
    if kept:
        logger.warning(f"Left {kept} slots alone rather than stage over them - see above.")
