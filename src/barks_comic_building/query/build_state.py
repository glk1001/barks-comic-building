"""Shared build-state predicates and flags for the status-reporting CLIs.

Every status report (`barks-fanta-info`, `barks-one-pager-info`,
`barks-cover-info`) grades a title against the same workflow ladder, so the
predicates and their single-letter flags live here rather than in any one report.

The ladder is strict: a state is reported only when every earlier step is
fulfilled, so the last flag in the ladder guarantees the whole workflow is done.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from barks_fantagraphics.comic_book import ModifiedType
from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES, STORY_PAGE_TYPES
from barks_fantagraphics.comics_utils import (
    dest_file_is_older_than_srce,
    get_max_timestamp,
    get_timestamp,
)
from barks_fantagraphics.fanta_comics_info import HAND_RESTORED_TITLES
from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comic_book import ComicBook

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


def is_upscayled(comic: ComicBook) -> bool:
    if comic.get_ini_title() in HAND_RESTORED_TITLES:
        return True

    return all_files_exist(
        [f[0] for f in comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES)]
    )


def is_restored(comic: ComicBook) -> bool:
    if comic.get_ini_title() in HAND_RESTORED_TITLES:
        return True

    return all_files_exist(comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES))


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


def has_panel_bounds(comic: ComicBook) -> bool:
    if not is_restored(comic):
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


def _dest_blocker(comic: ComicBook, newest_srce_timestamp: float, srce_desc: str) -> str | None:
    """Say why a comic's zip or its symlinks are missing or stale, or None if fine.

    Args:
        comic: The comic to check.
        newest_srce_timestamp: Timestamp of the newest file the build consumed.
        srce_desc: What those source files are, for the staleness message.

    Returns:
        The reason the built artifacts are not usable, or None if all are current.

    """
    zip_file = comic.get_dest_comic_zip()
    if not zip_file.is_file():
        return f'there is no zip file "{zip_file}"'
    zip_file_timestamp = get_timestamp(zip_file)

    if zip_file_timestamp < newest_srce_timestamp:
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

    return _dest_blocker(comic, get_max_timestamp(srce_files), "staged source images")


def _restore_blocker(comic: ComicBook) -> str | None:
    """Say why a comic's pages are not fully restored and panel-bounded, or None if fine.

    Mirrors the gates `has_panel_bounds` applies, in the same order, but reports how
    many pages fall at each one.

    Args:
        comic: The comic to check.

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


def get_build_blocker(comic: ComicBook) -> str | None:
    """Say why a comic is not built, or None when it is.

    The single source of truth for both the build state and the explanation of it -
    `is_built` is this function's verdict - so a report can never say "not built"
    without being able to say which step is outstanding.

    Args:
        comic: The comic to check.

    Returns:
        The reason the comic is not built, or None if it is built and current.

    """
    if not has_restorable_pages(comic):
        return _non_restorable_blocker(comic)

    blocker = _restore_blocker(comic)
    if blocker:
        return blocker

    panel_segments_files = comic.get_srce_panel_segments_files(RESTORABLE_PAGE_TYPES)
    return _dest_blocker(comic, get_max_timestamp(panel_segments_files), "panel segments files")


def is_built(comic: ComicBook) -> bool:
    blocker = get_build_blocker(comic)
    if blocker is not None:
        logger.debug(f'"{comic.ini_file}" is not built - {blocker}.')
        return False

    logger.debug(f'"{comic.ini_file}" has been built.')

    return True


def get_build_state_flag(comic: ComicBook) -> str:
    flag = CONFIGURED_FLAG

    restored = is_restored(comic)
    panels = has_panel_bounds(comic)

    if is_built(comic):
        flag = BUILT_FLAG
    elif has_inset_file(comic) and restored and panels:
        flag = INSET_FLAG
    elif panels:
        flag = PANELLED_FLAG
    elif restored:
        flag = RESTORED_FLAG
    elif is_upscayled(comic):
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
