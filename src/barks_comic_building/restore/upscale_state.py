"""Deciding whether a page still needs upscayling.

The old test was whether the upscayled png existed, which cannot tell a page made with the
current backend and settings from one made under settings that have since changed. The
library was upscayled with Upscayl and the default is now waifu2x, so on that test every
page reads as done and no amount of tuning would ever schedule a re-run.

The question asked properly is: is the output there, and was it made with the recipe in
force now.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

from barks_comic_building.restore.image_io import read_png_metadata

if TYPE_CHECKING:
    from pathlib import Path

# The png metadata keys the upscale stamps its provenance into.
RECIPE_ID_KEY = "Upscale recipe id"
RECIPE_KEY = "Upscale recipe"
UPSCALE_DATE_KEY = "Upscale date"


class UpscalePageState(StrEnum):
    """Where a page stands relative to the recipe in force now."""

    CURRENT = "current"
    """The output is present and was made with the current recipe. Nothing to do."""

    STALE = "stale"
    """The output is present, but made with different settings, or with none recorded.
    Every page upscayled before provenance was kept lands here."""

    MISSING = "missing"
    """The output does not exist."""

    LINKED = "linked"
    """The output is a symlink to a page of another volume, which owns it.

    Collection titles borrow pages this way - volume 1 carries a hundred of them - and
    the page they point at is upscayled as part of its own volume. Writing here would
    follow the link and overwrite that volume's page, with an upscale of a different
    source image, so a linked page is never this run's to make."""

    FIXES = "fixes"
    """The page is a hand-edited file in the upscayled fixes tree.

    A fixes file does not sit beside the upscayled page, it *is* what stands in for it:
    `get_final_srce_upscayled_story_file` returns the fixes file rather than the upscayled
    one, and refuses to let both exist. So the path an upscale would write to for such a
    page is the hand-edited file itself.

    Nothing an upscaler produces belongs there. The edit was made by hand, carries no
    recipe of ours, and cannot be made again by re-running anything - which is also why it
    reads as STALE on the recipe test and would otherwise be redone, and destroyed, on
    every single run. Never this run's to make, not even under --force."""

    HAND_RESTORED = "hand-restored"
    """The page's restoration was made by hand, so nothing downstream wants this upscale.

    Unlike FIXES, the path an upscale would write to here is an ordinary file in the plain
    upscayled tree, and overwriting it destroys nothing. The reason to skip is that it
    feeds nobody: the upscayled page exists only as the restore's input, and the restore
    leaves hand-restored pages alone. Volume 3's ten Silent Night pages cost four minutes
    and 231MB a run to make something no later stage reads."""

    NO_SRCE = "no-srce"
    """The original page is not there, so it cannot be upscayled at all."""

    @property
    def needs_upscayling(self) -> bool:
        """Whether a page in this state should be put through the upscale."""
        return self in (UpscalePageState.STALE, UpscalePageState.MISSING)


class UpscalePageStatus(NamedTuple):
    """A page's state, and the provenance behind it."""

    state: UpscalePageState
    recipe_id: str
    upscale_date: str

    @property
    def needs_upscayling(self) -> bool:
        """Whether this page should be put through the upscale."""
        return self.state.needs_upscayling


# One return per state: the body is a chain of guard clauses in the order the questions
# have to be asked, and collapsing them would hide the ordering, which is the point.
def get_upscale_page_status(  # noqa: PLR0911
    srce_file: Path,
    dest_upscayl_file: Path,
    current_recipe_id: str,
    *,
    is_fixes_file: bool,
    is_hand_restored: bool,
) -> UpscalePageStatus:
    """Work out whether a page still needs upscayling.

    Args:
        srce_file: The original page the upscale works from.
        dest_upscayl_file: The upscayled page.
        current_recipe_id: The id of the recipe the upscale would use now.
        is_fixes_file: Whether `dest_upscayl_file` is a hand-edited page in the upscayled
            fixes tree, which is what `get_final_srce_upscayled_story_file` returns a
            non-ORIGINAL `ModifiedType` for. Deliberately required rather than defaulted:
            a caller that forgets it queues the hand edit for overwriting, which is how
            five of them were lost.
        is_hand_restored: Whether this page's *restoration* was made by hand -
            `ComicBook.is_hand_restored`. Such a page's upscale feeds only the restore,
            which skips it, so making it is work for nothing. Required for the same reason
            as `is_fixes_file`.

    Returns:
        The page's state, with the recipe id and date read off the upscayled png when it
        has them.

    """
    # These three come first, and none of them looks at the recipe, because for all three
    # the question "is this page up to date" is not this run's to answer - and for the
    # first two, answering it here is done by destroying something.

    # A symlink is another volume's page, and whether it is up to date belongs to that
    # volume. Asked here it would be answered by writing through the link. Tested before
    # the fixes check because a page can be both - a link standing in this volume that
    # points into another's upscayled fixes tree - and the volume it belongs to is the
    # more useful of the two things to be told.
    if dest_upscayl_file.is_symlink():
        return UpscalePageStatus(UpscalePageState.LINKED, "", "")

    # A hand edit stands where the upscayled page would be. It has no recipe of ours, so
    # every recipe test calls it stale, and acting on that would overwrite it for good.
    if is_fixes_file:
        return UpscalePageStatus(UpscalePageState.FIXES, "", "")

    # The restoration of this page was made by hand, so the restore will not read the
    # upscayled page and nothing else ever does. Tested after the fixes check because a
    # page can be both - volume 4's 227 is - and FIXES is the one that names a file an
    # upscale would destroy rather than merely one it need not make.
    if is_hand_restored:
        return UpscalePageStatus(UpscalePageState.HAND_RESTORED, "", "")

    if not srce_file.is_file():
        return UpscalePageStatus(UpscalePageState.NO_SRCE, "", "")

    if not dest_upscayl_file.is_file():
        return UpscalePageStatus(UpscalePageState.MISSING, "", "")

    metadata = read_png_metadata(dest_upscayl_file)
    recipe_id = metadata.get(RECIPE_ID_KEY, "")
    upscale_date = metadata.get(UPSCALE_DATE_KEY, "")

    if recipe_id and recipe_id == current_recipe_id:
        return UpscalePageStatus(UpscalePageState.CURRENT, recipe_id, upscale_date)

    return UpscalePageStatus(UpscalePageState.STALE, recipe_id, upscale_date)
