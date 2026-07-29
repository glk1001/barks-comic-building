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

if TYPE_CHECKING:
    from pathlib import Path

# The png metadata keys the restore stamps its provenance into.
RECIPE_ID_KEY = "Restore recipe id"
RECIPE_KEY = "Restore recipe"
RESTORE_DATE_KEY = "Restore date"
UPSCALER_KEY = "Upscaler"


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


def get_page_status(
    srce_upscayl_file: Path,
    dest_restored_file: Path,
    dest_upscayled_restored_file: Path,
    dest_svg_restored_file: Path,
    current_recipe_id: str,
) -> PageStatus:
    """Work out whether a page still needs restoring.

    Args:
        srce_upscayl_file: The upscayled page the restore works from.
        dest_restored_file: The restored page at source size.
        dest_upscayled_restored_file: The restored page at full scale.
        dest_svg_restored_file: The traced line art.
        current_recipe_id: The id of the recipe the pipeline would use now.

    Returns:
        The page's state, with the recipe id and date read off the restored png when it
        has them.

    """
    outputs = [dest_restored_file, dest_upscayled_restored_file, dest_svg_restored_file]

    # Before anything else: a symlink among the outputs means this page is another
    # volume's, and whether it is up to date is that volume's question. Asked here it
    # would be answered by writing through the link.
    if any(file.is_symlink() for file in outputs):
        return PageStatus(PageState.LINKED, "", "")

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

    Args:
        srce_upscayl_file: The upscayled page.

    Returns:
        The upscaler name, or an empty string if the file predates that metadata.

    """
    return read_png_metadata(srce_upscayl_file).get(UPSCALER_KEY, "")
