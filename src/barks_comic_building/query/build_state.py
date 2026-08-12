"""Shared build-state predicates and flags for the status-reporting CLIs.

Every status report (`barks-fanta-info`, `barks-one-pager-info`,
`barks-cover-info`) grades a title against the same workflow ladder, so the
predicates and their single-letter flags live here rather than in any one report.

The ladder is strict: a state is reported only when every earlier step is
fulfilled, so the last flag in the ladder guarantees the whole workflow is done.

Strict about timestamps as well as about files. Each stage of the restore pipeline is
made *from* the one before it, so a stage that is newer than the thing derived from it
means that thing is out of date however complete it looks. The ladder used to compare
only two adjacent links - the panel segments against the restored page, and the zip
against the panel segments - and so reported a title as built when its zip, its pages
and its restored art all predated the upscayled files they were made from. Grading the
whole chain is `get_chain_state`, which uses the same verdict functions as
`barks-check-build` rather than a second opinion about the same files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from barks_fantagraphics.comic_book import ModifiedType
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES, STORY_PAGE_TYPES
from barks_fantagraphics.comics_utils import (
    dest_file_is_older_than_srce,
    get_timestamp,
)
from barks_fantagraphics.fanta_comics_info import HAND_RESTORED_TITLES
from barks_fantagraphics.pages import get_restored_srce_dependencies, get_sorted_srce_and_dest_pages
from loguru import logger

from barks_comic_building.build.utils import (
    MaxTimestamp,
    dating_dependencies,
    fold_max,
    is_stale,
    quiet_panel_bbox_height_warnings,
    walk_srce_dependency_chain,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from barks_fantagraphics.comic_book import ComicBook
    from barks_fantagraphics.pages import SrceDependency

# Row and cell styles shared by the status reports.
# A row that has not reached the last rung of its ladder.
NOT_DONE_STYLE = "orange1"
# A cell naming something actionable that is wrong - always applied to the cell
# rather than the row, so it stays visible on an already-NOT_DONE_STYLE row.
PROBLEM_STYLE = "red"
# The footer line of a report whose collection is built.
BUILT_STYLE = "green"

EMPTY_FLAG = " "
FIXES_FLAG = "F"

NOT_CONFIGURED_FLAG = "X"
CONFIGURED_FLAG = "C"
PAYMENTS_FLAG = "$"
UPSCAYLED_FLAG = "U"
RESTORED_FLAG = "R"
PANELLED_FLAG = "P"
INSET_FLAG = "I"
BUILT_FLAG = "B"

BUILD_STATE_FLAGS = [
    NOT_CONFIGURED_FLAG,
    CONFIGURED_FLAG,
    PAYMENTS_FLAG,
    UPSCAYLED_FLAG,
    RESTORED_FLAG,
    PANELLED_FLAG,
    INSET_FLAG,
    BUILT_FLAG,
]


def all_files_exist(file_list: list[Path]) -> bool:
    if not file_list:
        return False

    return all(file.is_file() for file in file_list)


# Which rung of the ladder an inverted pair implicates. The *older* file of the pair is
# the one that needs remaking, so it is the one that names the rung - a restored page
# older than the upscayl behind it is a restore to re-run, not an upscayl.
_UPSCAYL_RUNG = "upscayl"
_RESTORE_RUNG = "restore"
_PANELS_RUNG = "panels"


@dataclass(frozen=True, slots=True)
class ChainState:
    """What a comic's source restore chains say about how current its stages are.

    Every timestamp question the ladder asks reads the same files, so they are answered
    from one scan rather than one scan per rung. That also stops two rungs disagreeing
    about a tree that is being written to while the report runs.
    """

    # Pages whose upscayled file predates the original scan it was made from.
    stale_upscayl_pages: int
    # Pages whose restored art predates something further down its chain.
    stale_restore_pages: int
    # Pages that had a chain to grade at all.
    total_pages: int
    # The newest source of any page, the intro inset and bounds overrides included.
    max_srce: MaxTimestamp | None


# What a comic with nothing to compare grades as: no restorable pages, or a page list
# that will not resolve. Neither is a staleness finding - the existence rungs report
# both already - so an empty scan must never be the thing that demotes a title.
CLEAN_CHAIN = ChainState(
    stale_upscayl_pages=0,
    stale_restore_pages=0,
    total_pages=0,
    max_srce=None,
)


def _rung_by_dir(comic: ComicBook) -> dict[Path, str]:
    """Map each tree of the restore chain to the rung that produces it.

    By tree rather than by position in the chain: the chain skips its intermediate
    stages for a page whose fixes were added rather than restored, so a stage's index
    does not identify it, and the trees are what `has_restored_file_in_chain` already
    keys on.

    Args:
        comic: The comic whose trees to map.

    Returns:
        The directory of each stage, against the rung it belongs to.

    """
    return {
        comic.dirs.panel_segments_dir: _PANELS_RUNG,
        comic.get_srce_restored_image_dir(): _RESTORE_RUNG,
        comic.get_srce_restored_upscayled_image_dir(): _RESTORE_RUNG,
        comic.get_srce_restored_svg_image_dir(): _RESTORE_RUNG,
        comic.get_srce_upscayled_image_dir(): _UPSCAYL_RUNG,
        comic.get_srce_upscayled_fixes_image_dir(): _UPSCAYL_RUNG,
    }


def on_disk_chain(dependencies: Sequence[SrceDependency]) -> list[SrceDependency]:
    """Return the stages of a page's chain that are actually there to be compared.

    Independent dependencies - the intro inset, a hand-drawn bounds override - are not
    part of the chain, because nothing was derived from them.

    A stage that is not on disk goes too, which is where this parts company with the
    integrity checker. `walk_srce_dependency_chain` treats its missing-stage sentinel as
    an inversion, which is right for a fault report; here existence is already the
    business of `is_upscayled` and `is_restored`, and counting it a second time in
    timestamps demoted every title whose pages legitimately have no upscayled or svg
    stage behind them at all.

    Args:
        dependencies: The page's dependencies, as the pipeline reports them.

    Returns:
        The comparable stages, latest first.

    """
    return [d for d in dependencies if not d.independent and d.timestamp >= 0]


def stale_chain_rungs(
    chain: Sequence[SrceDependency],
    rung_by_dir: Mapping[Path, str],
    max_srce: MaxTimestamp | None,
) -> tuple[frozenset[str], MaxTimestamp | None]:
    """Walk one page's chain and name the rungs whose output it has outrun.

    Args:
        chain: The page's comparable stages, latest first, from `on_disk_chain`.
        rung_by_dir: Which rung each stage's tree belongs to, from `_rung_by_dir`.
        max_srce: The running newest-source maximum to fold this page into.

    Returns:
        The rungs that need re-running, and the updated maximum.

    """
    # Only the intro inset lives inside a zip and it is always independent, so this
    # narrows rather than discards. Narrowing at the head is what keeps the walk's pairs
    # plain `Path`s all the way to the rung lookup below.
    head_file = chain[0].file if chain else None
    if not isinstance(head_file, Path):
        return frozenset(), max_srce

    staleness = walk_srce_dependency_chain(
        chain[1:], head_file, chain[0].timestamp, max_srce, is_a_comic=True
    )

    # Unrecognised trees are the collections' fallback from a missing restored page to
    # its staged scan. Calling that a restore is the actionable answer.
    rungs = frozenset(
        rung_by_dir.get(older.parent, _RESTORE_RUNG) for _newer, older in staleness.stale_pairs
    )

    return rungs, fold_max(staleness.max_srce, head_file, chain[0].timestamp)


def get_chain_state(comic: ComicBook) -> ChainState:
    """Grade every page's restore chain, and collect the newest source of the title.

    Walks the same chain as `barks-check-build`, through the same
    `walk_srce_dependency_chain`, so the two reports cannot come to opposite conclusions
    about one title. A page list that will not resolve grades as clean rather than
    raising, and the pages are resolved with the timestamp check off, both for the same
    reason: that check raises on exactly the fault this report exists to display.

    Args:
        comic: The comic to grade.

    Returns:
        The per-rung staleness counts and the title's newest source file.

    """
    if not has_restorable_pages(comic):
        return CLEAN_CHAIN

    try:
        with quiet_panel_bbox_height_warnings():
            pages = get_sorted_srce_and_dest_pages(
                comic, get_full_paths=True, check_srce_page_timestamps=False
            )
    except Exception as e:  # noqa: BLE001
        logger.debug(f'Cannot read the pages of "{comic.ini_file}" to date them - {e}.')
        return CLEAN_CHAIN

    rung_by_dir = _rung_by_dir(comic)
    max_srce: MaxTimestamp | None = None
    stale_upscayl = 0
    stale_restore = 0
    total_pages = 0

    for srce_page in pages.srce_pages:
        # The ini file is git-tracked, so its mtime dates a checkout rather than an edit.
        dependencies = dating_dependencies(
            get_restored_srce_dependencies(comic, srce_page), comic.ini_file
        )

        # The independent ones are out of the chain but still raise the maximum: an
        # edited inset or bounds override really does mean the page needs rebuilding.
        for dependency in dependencies:
            if dependency.independent:
                max_srce = fold_max(max_srce, dependency.file, dependency.timestamp)

        chain = on_disk_chain(dependencies)
        if not chain:
            continue

        total_pages += 1
        rungs, max_srce = stale_chain_rungs(chain, rung_by_dir, max_srce)
        if _UPSCAYL_RUNG in rungs:
            stale_upscayl += 1
        if _RESTORE_RUNG in rungs:
            stale_restore += 1

    return ChainState(stale_upscayl, stale_restore, total_pages, max_srce)


def is_upscayled(comic: ComicBook, chain: ChainState | None = None) -> bool:
    if comic.get_ini_title() in HAND_RESTORED_TITLES:
        return True

    if not all_files_exist(
        [f[0] for f in comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)]
    ):
        return False

    # Existence first: it is the cheaper question, and a missing file is the finding to
    # report when both are true.
    chain = get_chain_state(comic) if chain is None else chain

    return chain.stale_upscayl_pages == 0


def is_restored(comic: ComicBook, chain: ChainState | None = None) -> bool:
    if comic.get_ini_title() in HAND_RESTORED_TITLES:
        return True

    if not all_files_exist(comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)):
        return False

    chain = get_chain_state(comic) if chain is None else chain

    # A restore made from a stale upscayl is not current either, so the earlier rung's
    # count blocks this one - that is what makes the ladder strict.
    return chain.stale_upscayl_pages == 0 and chain.stale_restore_pages == 0


def has_inset_file(comic: ComicBook) -> bool:
    return comic.intro_inset_file.is_file()


def has_fixes(comic: ComicBook) -> bool:
    mods = [
        f[1]
        for f in comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES)
        if f[1] != ModifiedType.ORIGINAL
    ]
    if any(mods):
        return True

    mods = [
        f[1]
        for f in comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)
        if f[1] != ModifiedType.ORIGINAL
    ]
    return any(mods)


def has_panel_bounds(comic: ComicBook, chain: ChainState | None = None) -> bool:
    if not is_restored(comic, chain):
        return False
    if not all_files_exist(comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES)):
        return False
    if comic.get_ini_title() in HAND_RESTORED_TITLES:
        return True

    restored_files = comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)
    panel_segments_files = comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES)

    for restored_file, panel_segments_file in zip(
        restored_files, panel_segments_files, strict=True
    ):
        if dest_file_is_older_than_srce(restored_file, panel_segments_file):
            logger.debug(
                f'Panels segments file "{panel_segments_file}" is'
                f' out of date WRT restored file "{restored_file}".'
            )
            return False

    return True


def has_restorable_pages(comic: ComicBook) -> bool:
    """Return whether any of a comic's story pages goes through the restore pipeline.

    False only for a title made up entirely of non-restorable pages - in practice
    the all-`COVER` "All Covers" collection. Such a title never gets a restored
    image or a panel-segments file, so the restore/panel rungs of the build ladder
    do not apply to it (see `is_built`).

    Args:
        comic: The comic to inspect.

    Returns:
        True if the comic has at least one page in `RESTORABLE_PAGE_TYPES`.

    """
    return bool(comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES))


def _missing_files(file_list: list[Path]) -> list[Path]:
    """Return the files in a list that are not on disk."""
    return [f for f in file_list if not f.is_file()]


def _symlink_blocker(symlink: Path, zip_file_timestamp: float, which: str) -> str | None:
    """Say why one of a comic's zip symlinks is missing or stale, or None if it is fine.

    Args:
        symlink: The symlink to check.
        zip_file_timestamp: Timestamp of the comic's zip file.
        which: Which symlink this is ("series" or "year"), for the message.

    Returns:
        The reason the symlink is not usable, or None if it is present and current.

    """
    if not symlink.is_symlink():
        return f'there is no {which} symlink "{symlink}"'

    if get_timestamp(symlink) < zip_file_timestamp:
        return f"the {which} symlink is older than the zip file"

    return None


def _dest_blocker(comic: ComicBook, max_srce: MaxTimestamp | None, srce_desc: str) -> str | None:
    """Say why a comic's built artifacts are missing or stale, or None if fine.

    The build is dated by its metadata file as well as by its zip. That file is written
    by a build and by nothing else, whereas the zip and its symlinks get remade on their
    own - one title's symlinks are dated a week after the zip they point at, which is
    itself a week after the pages inside it - so the archive's mtime alone is not
    evidence that a build has run since its sources changed.

    Args:
        comic: The comic to check.
        max_srce: The newest file the build consumed, or None if it could not be worked
            out - in which case nothing is graded stale, as a check that cannot name its
            inputs should report nothing rather than everything.
        srce_desc: What those source files are, for the staleness message.

    Returns:
        The reason the built artifacts are not usable, or None if all are current.

    """
    zip_file = comic.get_dest_comic_zip()
    if not zip_file.is_file():
        return f'there is no zip file "{zip_file}"'

    metadata_file = comic.get_metadata_filepath()
    if not metadata_file.is_file():
        return f'there is no build metadata file "{metadata_file}"'
    if is_stale(get_timestamp(metadata_file), max_srce):
        return f"the build is older than its {srce_desc}"

    zip_file_timestamp = get_timestamp(zip_file)
    if is_stale(zip_file_timestamp, max_srce):
        return f"the zip file is older than its {srce_desc}"

    return _symlink_blocker(
        comic.get_dest_series_comic_zip_symlink(), zip_file_timestamp, "series"
    ) or _symlink_blocker(comic.get_dest_year_comic_zip_symlink(), zip_file_timestamp, "year")


def _non_restorable_blocker(comic: ComicBook) -> str | None:
    """Say why an all-non-restorable-pages comic is not built, or None if it is.

    The restore and panel-bounds rungs cannot apply to a title whose every page is
    a `COVER` (it is built full-page, never restored or cropped to panels), so the
    only questions left are whether its source images are staged and whether the
    zip and symlinks are present and newer than those images.

    Args:
        comic: The comic to check.

    Returns:
        The reason it is not built, or None if it is.

    """
    srce_files = [f[0] for f in comic.get_final_srce_story_files(STORY_PAGE_TYPES)]
    if not srce_files:
        return "it has no pages"

    missing = _missing_files(srce_files)
    if missing:
        return f"{len(missing)} of its {len(srce_files)} pages are not staged"

    max_srce: MaxTimestamp | None = None
    for file in srce_files:
        max_srce = fold_max(max_srce, file, get_timestamp(file))

    return _dest_blocker(comic, max_srce, "staged source images")


def _stale_chain_blocker(chain: ChainState) -> str | None:
    """Say which restore stage a comic's chains have outrun, or None if none has.

    In ladder order, so the step named is the earliest one that has to be re-run: a
    restore made from a stale upscayl needs the upscayl doing first.

    Args:
        chain: The comic's graded restore chains.

    Returns:
        The outstanding stage, or None if every chain is in order.

    """
    if chain.stale_upscayl_pages:
        return (
            f"{chain.stale_upscayl_pages} of its {chain.total_pages} pages have an"
            f" upscayled file older than its original scan"
        )

    if chain.stale_restore_pages:
        return (
            f"{chain.stale_restore_pages} of its {chain.total_pages} pages have"
            f" restored art older than its upscayled source"
        )

    return None


def _restore_blocker(comic: ComicBook, chain: ChainState) -> str | None:
    """Say why a comic's pages are not fully restored and panel-bounded, or None if fine.

    Mirrors the gates `has_panel_bounds` applies, in the same order, but reports how
    many pages fall at each one. Existence is asked before staleness throughout: a file
    that is not there is the thing to say about it, and saying it a second way in
    timestamps only pads the answer.

    Args:
        comic: The comic to check.
        chain: The comic's already-graded restore chains.

    Returns:
        The reason the restore workflow is incomplete, or None if it is done.

    """
    hand_restored = comic.get_ini_title() in HAND_RESTORED_TITLES
    restored_files = comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES)
    panel_segments_files = comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES)

    if not hand_restored:
        missing = _missing_files(restored_files)
        if missing:
            return f"{len(missing)} of its {len(restored_files)} pages are not restored"

    missing = _missing_files(panel_segments_files)
    if missing:
        return (
            f"{len(missing)} of its {len(panel_segments_files)} pages have no panel segments file"
        )

    if hand_restored:
        return None

    blocker = _stale_chain_blocker(chain)
    if blocker:
        return blocker

    stale = [
        panel_segments_file
        for restored_file, panel_segments_file in zip(
            restored_files, panel_segments_files, strict=True
        )
        if dest_file_is_older_than_srce(restored_file, panel_segments_file)
    ]
    if stale:
        return (
            f"{len(stale)} of its {len(panel_segments_files)} panel segments files"
            f" are older than their restored page"
        )

    return None


def get_build_blocker(comic: ComicBook, chain: ChainState | None = None) -> str | None:
    """Say why a comic is not built, or None when it is.

    The single source of truth for both the build state and the explanation of it -
    `is_built` is this function's verdict - so a report can never say "not built"
    without being able to say which step is outstanding.

    Args:
        comic: The comic to check.
        chain: The comic's already-graded restore chains, if the caller has them.

    Returns:
        The reason the comic is not built, or None if it is built and current.

    """
    if not has_restorable_pages(comic):
        return _non_restorable_blocker(comic)

    chain = get_chain_state(comic) if chain is None else chain

    blocker = _restore_blocker(comic, chain)
    if blocker:
        return blocker

    # Against the newest file anywhere in the chain, not just the panel segments. Those
    # are only the last stage before the build, so timing the zip against them alone
    # said nothing about a re-upscayl that the restore had never been re-run over.
    return _dest_blocker(comic, chain.max_srce, "source files")


def is_built(comic: ComicBook, chain: ChainState | None = None) -> bool:
    blocker = get_build_blocker(comic, chain)
    if blocker is not None:
        logger.debug(f'"{comic.ini_file}" is not built - {blocker}.')
        return False

    logger.debug(f'"{comic.ini_file}" has been built.')

    return True


def get_build_state_flag(comic: ComicBook) -> str:
    flag = CONFIGURED_FLAG

    # Scanned once and threaded through every rung below. The rungs all read the same
    # files, so scanning per rung would stat each page four times over and let two rungs
    # answer from different reads of a tree that is still being written to.
    chain = get_chain_state(comic)

    restored = is_restored(comic, chain)
    panels = has_panel_bounds(comic, chain)

    if is_built(comic, chain):
        flag = BUILT_FLAG
    elif has_inset_file(comic) and restored and panels:
        flag = INSET_FLAG
    elif panels:
        flag = PANELLED_FLAG
    elif restored:
        flag = RESTORED_FLAG
    elif is_upscayled(comic, chain):
        flag = UPSCAYLED_FLAG

    return flag


def get_staged_link_stem(staged_links: list[tuple[Path, Path]] | None) -> str:
    """Return the page stem a title's staged links share, or "" if it has none.

    Every artifact of one collection member is staged under the same collection page
    number - "500.jpg", "500.png", "500.svg.png", "500.json" - so the stem doubles as
    the member's page within its collection. Split on the first dot rather than using
    `Path.stem`, which would leave "500.svg" for the ".svg.png" link.

    Args:
        staged_links: The title's `(link, source)` candidates, or None if unlocated.

    Returns:
        The shared stem, or "" when the title has no staged links.

    """
    if not staged_links:
        return ""

    link, _ = staged_links[0]

    return link.name.split(".", 1)[0]


def get_state_filter(state_arg: str, valid_flags: list[str]) -> list[str]:
    """Parse a comma-separated build-state filter argument.

    Args:
        state_arg: The raw `--state` value; empty means "no filter".
        valid_flags: The flags the calling report can actually produce.

    Returns:
        The flags to keep - all of `valid_flags` when `state_arg` is empty.

    Raises:
        RuntimeError: If any requested flag is not in `valid_flags`.

    """
    if not state_arg:
        return valid_flags

    filt = state_arg.split(",")
    if not set(filt).issubset(set(valid_flags)):
        msg = f'Not a valid state filter: "{filt}". Valid states: {valid_flags}.'
        raise RuntimeError(msg)

    return filt
