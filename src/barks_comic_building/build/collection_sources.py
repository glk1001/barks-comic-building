"""Which of a volume's scans a synthetic collection stages a page from.

"All Covers" and "All One-Pagers" are assembled by linking one page out of some other
volume, and that page can exist in more than one tree. The rule for choosing between
them is not this module's to invent: it belongs to the build, in
`ComicBook._get_final_story_file`, and it is that a *fixes* file, when present,
overrides the original. That is the only reason the fixes tree exists - a page is put
there precisely because its original is not the version to use.

Staging used to have that backwards, taking the volume's original and reading its fixes
file only when the original was missing. Nothing failed and nothing looked wrong: every
staged page was a valid image, just the unedited one, with timestamps that agreed
perfectly. Nine covers built from originals whose edits had been made weeks earlier.
This is the same silent-wrong-image failure mode `check_collection_staged_links` exists
for, so the two now agree by construction - that check compares each on-disk link
against the source these functions name.

Two narrower mismatches went with it, both latent rather than live today:

* A fixes scan may be ``.jpg`` *or* ``.png`` (see
  `ComicBook.get_srce_original_fixes_story_file`); staging only ever looked for ``.jpg``.
  A ``.png`` fix was therefore not merely lost - it was invisible, and the original was
  staged in its place with no sign anything had been skipped.
* The upscayled candidate read only the upscayled tree, never the upscayled-fixes tree
  beside it, so a hand-fixed upscayl was dropped the same way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from comic_utils.comic_consts import JPG_FILE_EXT, PNG_FILE_EXT

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comics_database import ComicsDatabase

# A fixes scan is stored in whichever of these its editor saved; an original is always
# a jpg and an upscayl always a png.
FIXES_EXTS = (JPG_FILE_EXT, PNG_FILE_EXT)


def _sole_fixes_file(fixes_dir: Path, page: str) -> Path | None:
    """Return the volume's fixes file for ``page``, or None if it has none.

    Raises:
        RuntimeError: If the page has both a ``.jpg`` and a ``.png`` fixes file. Which
            one supersedes the original is then unanswerable, and picking either would
            stage an image nobody chose. `ComicBook.get_srce_original_fixes_story_file`
            refuses the same pair for the same reason.

    """
    found = [fixes_dir / (page + ext) for ext in FIXES_EXTS]
    found = [path for path in found if path.is_file()]

    if len(found) > 1:
        msg = f'Cannot have both .jpg and .png fixes file "{found[0]}".'
        raise RuntimeError(msg)

    return found[0] if found else None


def original_scan_source(comics_database: ComicsDatabase, volume: int, page: str) -> Path:
    """Return the scan a collection page should be staged from.

    The volume's fixes file when it has one - in either extension - and otherwise its
    read-only original. The returned path is not promised to exist: a volume with
    neither yields the original's path, and the caller stages only existing sources so
    that a page not yet scanned stays outstanding work rather than becoming an error
    here.

    Args:
        comics_database: The database supplying the volume directory paths.
        volume: The Fantagraphics volume the page is taken from.
        page: The page number in that volume, zero-padded (see `get_page_str`).

    Returns:
        The path to stage the collection's original-scan slot from.

    """
    fixes = _sole_fixes_file(comics_database.get_fantagraphics_fixes_volume_image_dir(volume), page)
    if fixes is not None:
        return fixes

    return comics_database.get_fantagraphics_volume_image_dir(volume) / (page + JPG_FILE_EXT)


def upscayled_scan_source(comics_database: ComicsDatabase, volume: int, page: str) -> Path:
    """Return the upscayled image a collection page should be staged from.

    Same precedence as `original_scan_source`, over the upscayled pair of trees. Only
    ``.png`` is considered: `ComicBook.get_final_srce_upscayled_story_file` rejects a
    ``.jpg`` upscayled fix outright, so honouring one here would stage a file the build
    then refuses.

    Args:
        comics_database: The database supplying the volume directory paths.
        volume: The Fantagraphics volume the page is taken from.
        page: The page number in that volume, zero-padded (see `get_page_str`).

    Returns:
        The path to stage the collection's upscayled slot from.

    """
    fixes = comics_database.get_fantagraphics_upscayled_fixes_volume_image_dir(volume) / (
        page + PNG_FILE_EXT
    )
    if fixes.is_file():
        return fixes

    return comics_database.get_fantagraphics_upscayled_volume_image_dir(volume) / (
        page + PNG_FILE_EXT
    )


def staged_link_for(dest_dir: Path, collection_page: str, source: Path) -> Path:
    """Return the collection slot ``source`` is staged into, named after ``source``.

    The slot takes the source's own extension rather than a fixed ``.jpg``, because a
    ``.png`` fix staged under a ``.jpg`` name is a png file that every later stage reads
    as a jpg by its name. `ComicBook.get_srce_original_fixes_story_file` looks for both
    extensions in this directory, so either name resolves.

    Args:
        dest_dir: The collection's image dir the slot lives in.
        collection_page: The collection page number, zero-padded.
        source: The file being staged, whose extension the slot inherits.

    Returns:
        The path of the staged link.

    """
    return dest_dir / (collection_page + source.suffix)


def superseded_links(link: Path) -> list[Path]:
    """Return the staged slots ``link`` replaces - same page, other extension.

    Restaging a page whose fix changed extension would otherwise leave the old slot
    beside the new one, and two fixes files for one page is exactly the pair
    `_sole_fixes_file` and the build both refuse. A same-stem sibling is always a
    previous staging of this page: the fixes tree is the only one a collection is staged
    into that holds both extensions, and the pipeline's own output beside it -
    ``barks-batch-upscayl`` writes a real ``.png`` into the collection's upscayled dir -
    is never named here, because a slot never lists its own extension as superseded.

    Args:
        link: The slot about to be staged.

    Returns:
        The existing sibling slots to remove first; usually empty.

    """
    siblings = [link.with_suffix(ext) for ext in FIXES_EXTS if ext != link.suffix]

    return [path for path in siblings if path.is_symlink() or path.exists()]
