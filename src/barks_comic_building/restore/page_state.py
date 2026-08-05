"""Deciding whether a page still needs restoring.

The old test was whether the restored png existed. That misses two things. It cannot tell
a page made with the current tuning from one made under settings that have since changed,
so a re-run after a tuning change meant deleting outputs by hand. And it looks at only one
of the three files a restore produces, so a page whose 4x or svg output never got written
was skipped from then on - there are over a hundred such pages in the library today,
mostly in volumes 1 and 7.

Both are the same question asked properly: are all of this page's outputs present, and
were they made with the recipe in force now.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

from barks_comic_building.restore.image_io import read_png_metadata
from barks_comic_building.restore.upscale_image import (
    UPSCALER_KEY,
    UPSCAYL_MODEL_KEY,
    WAIFU2X_MODEL_KEY,
    Upscaler,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "UPSCALER_KEY",
    "PageState",
    "PageStatus",
    "get_page_status",
    "get_upscaler_used",
]

# The png metadata keys the restore stamps its provenance into.
RECIPE_ID_KEY = "Restore recipe id"
RECIPE_KEY = "Restore recipe"
RESTORE_DATE_KEY = "Restore date"


class PageState(StrEnum):
    """Where a page stands relative to the recipe in force now."""

    CURRENT = "current"
    """Every output is present and was made with the current recipe. Nothing to do."""

    STALE = "stale"
    """Every output is present, but made with different settings, or with none recorded.
    Pages restored before provenance was kept land here, which is what makes the first
    run after this change redo the library without anything being deleted first."""

    INCOMPLETE = "incomplete"
    """Some outputs exist and some do not. Under the old existence check these were
    invisible whenever the restored png happened to be one of the ones present."""

    MISSING = "missing"
    """None of the outputs exist."""

    LINKED = "linked"
    """An output is a symlink to a page of another volume, which owns it.

    Collection titles borrow pages this way - volume 1 carries a hundred of them - and
    the page they point at is restored as part of its own volume. Writing here would
    follow the link and overwrite that volume's page, from a different source image, so
    a linked page is never this run's to make."""

    HAND_RESTORED = "hand-restored"
    """The restored page was made by hand, and is what a run would write over.

    Two kinds, both declared in `HAND_RESTORED_TITLES` / `HAND_RESTORED_PAGES` rather than
    detected. A page of a hand-restored title, whose restored output the build never even
    reads - `get_final_srce_story_file` goes to the fixes tree for those titles. And an
    individually declared page like volume 4's 227, whose restored png *is* the hand work.

    Neither carries a recipe of ours, so the recipe test calls both stale and a run would
    redo them: the first wasting hours on output nothing consumes, the second destroying a
    page that no re-run can make again. Declared rather than detected because the only
    trace on disk is a missing metadata key, which is also what an interrupted write
    leaves. Never this run's to make, not even under --force."""

    NO_SRCE = "no-srce"
    """The upscayled input is not there, so the page cannot be restored at all."""

    @property
    def needs_restoring(self) -> bool:
        """Whether a page in this state should be put through the pipeline."""
        return self in (PageState.STALE, PageState.INCOMPLETE, PageState.MISSING)


class PageStatus(NamedTuple):
    """A page's state, and the provenance behind it."""

    state: PageState
    recipe_id: str
    restore_date: str

    @property
    def needs_restoring(self) -> bool:
        """Whether this page should be put through the pipeline."""
        return self.state.needs_restoring


# One parameter per thing the answer depends on, and one return per state, because the
# body is a chain of guard clauses in the order the questions have to be asked. Collapsing
# either would hide the ordering, which is the part that matters here.
def get_page_status(  # noqa: PLR0911, PLR0913
    srce_upscayl_file: Path,
    dest_restored_file: Path,
    dest_upscayled_restored_file: Path,
    dest_svg_restored_file: Path,
    current_recipe_id: str,
    *,
    is_hand_restored: bool,
) -> PageStatus:
    """Work out whether a page still needs restoring.

    Args:
        srce_upscayl_file: The upscayled page the restore works from.
        dest_restored_file: The restored page at source size.
        dest_upscayled_restored_file: The restored page at full scale.
        dest_svg_restored_file: The traced line art.
        current_recipe_id: The id of the recipe the pipeline would use now.
        is_hand_restored: Whether this page's restored file was made by hand -
            `ComicBook.is_hand_restored`. Deliberately required rather than defaulted: a
            caller that forgets it queues the hand work for overwriting, which is exactly
            how volume 4's page 227 came to be one run away from being lost.

    Returns:
        The page's state, with the recipe id and date read off the restored png when it
        has them.

    """
    outputs = [dest_restored_file, dest_upscayled_restored_file, dest_svg_restored_file]

    # These two come first, and neither looks at the recipe, because for both the question
    # "is this page up to date" is not this run's to answer - and answering it here is done
    # by destroying something.

    # A symlink among the outputs means this page is another volume's, and whether it is up
    # to date is that volume's question. Asked here it would be answered by writing through
    # the link. Tested before the hand-restored check because a page can be both, and the
    # volume that owns it is the more useful of the two things to be told.
    if any(file.is_symlink() for file in outputs):
        return PageStatus(PageState.LINKED, "", "")

    # Made by hand. This is deliberately answered before anything about the input or which
    # outputs exist: those describe the page's ancestry, while this describes whose work
    # the output is. Volume 4's 227 has no original scan and is spared NO_SRCE today only
    # because its upscayled-fixes png happens to exist; and if a hand page's outputs were
    # deleted, a run must still not put a machine restore in their place.
    if is_hand_restored:
        return PageStatus(PageState.HAND_RESTORED, "", "")

    if not srce_upscayl_file.is_file():
        return PageStatus(PageState.NO_SRCE, "", "")

    num_present = sum(1 for file in outputs if file.is_file())

    if num_present == 0:
        return PageStatus(PageState.MISSING, "", "")

    if num_present < len(outputs):
        return PageStatus(PageState.INCOMPLETE, "", "")

    metadata = read_png_metadata(dest_restored_file)
    recipe_id = metadata.get(RECIPE_ID_KEY, "")
    restore_date = metadata.get(RESTORE_DATE_KEY, "")

    if recipe_id and recipe_id == current_recipe_id:
        return PageStatus(PageState.CURRENT, recipe_id, restore_date)

    return PageStatus(PageState.STALE, recipe_id, restore_date)


def get_upscaler_used(srce_upscayl_file: Path) -> str:
    """Return which upscaler made a page's input, from that file's own metadata.

    Upstream provenance rather than part of the restore recipe: it describes the input
    the restore was handed, not what the restore did with it.

    Pages upscayled before the "Upscaler" key existed - which is the whole library as it
    stands - carry only their backend's model key. That names the backend just as
    definitely, so it is read as a fallback rather than leaving the field blank on every
    page until the library has been through the upscale again.

    Args:
        srce_upscayl_file: The upscayled page.

    Returns:
        The upscaler name, or an empty string if the file has no metadata at all.

    """
    metadata = read_png_metadata(srce_upscayl_file)

    upscaler = metadata.get(UPSCALER_KEY, "")
    if upscaler:
        return upscaler

    if UPSCAYL_MODEL_KEY in metadata:
        return str(Upscaler.UPSCAYL)
    if WAIFU2X_MODEL_KEY in metadata:
        return str(Upscaler.WAIFU2X)

    return ""
