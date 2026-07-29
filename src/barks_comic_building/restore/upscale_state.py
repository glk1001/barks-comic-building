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


def get_upscale_page_status(
    srce_file: Path,
    dest_upscayl_file: Path,
    current_recipe_id: str,
) -> UpscalePageStatus:
    """Work out whether a page still needs upscayling.

    Args:
        srce_file: The original page the upscale works from.
        dest_upscayl_file: The upscayled page.
        current_recipe_id: The id of the recipe the upscale would use now.

    Returns:
        The page's state, with the recipe id and date read off the upscayled png when it
        has them.

    """
    # Before anything else: a symlink is another volume's page, and the question of
    # whether it is up to date belongs to that volume. Asked here it would be answered by
    # writing through the link.
    if dest_upscayl_file.is_symlink():
        return UpscalePageStatus(UpscalePageState.LINKED, "", "")

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
