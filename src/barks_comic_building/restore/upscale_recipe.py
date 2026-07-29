"""The set of settings that decide what an upscayled page comes out looking like.

The same argument as the restore recipe, one stage earlier. An upscayled page is only as
good as the backend and the settings that made it, and those change: the library was built
with Upscayl and its ultramix_balanced model, and the default is now waifu2x. Once the
model or the denoise level moves, every page made before the move is out of date, and
5,500 pages is far too many to work out by hand.

So the upscale records what it used, both in the page's png metadata and in the run
ledger, and compares them on the next run. A page whose recipe matches is finished;
anything else is done again. Changing WAIFU2X_NOISE_LEVEL, or the model, or the backend,
is therefore all it takes to schedule the re-run it implies.

Settings that belong to the backend not in use are held at a fixed sentinel rather than
their live value, so that tuning Upscayl does not invalidate pages made with waifu2x, or
the other way round.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from barks_comic_building.restore.upscale_image import (
    UPSCAYL_MODEL,
    UPSCAYL_TILE_SIZE,
    WAIFU2X_MODEL,
    WAIFU2X_NOISE_LEVEL,
    Upscaler,
)

# Bumped when the shape of a recipe changes in a way that makes old ids incomparable.
# Part of the hashed content, so bumping it invalidates every page.
RECIPE_VERSION = 1

_RECIPE_ID_LENGTH = 12

# Stands in for a setting the chosen backend does not have, so that the two backends'
# settings cannot invalidate each other's pages.
NOT_APPLICABLE = -1


@dataclass(frozen=True, slots=True)
class UpscaleRecipe:
    """Every setting that changes what an upscayled page looks like.

    Deliberately flat and made of plain values, so that ``as_dict`` round trips through
    json and a reader needs nothing from this package to make sense of it.
    """

    recipe_version: int
    upscaler: str
    scale: int
    model: str

    # waifu2x only. NOT_APPLICABLE under Upscayl.
    noise_level: int

    # Upscayl only. NOT_APPLICABLE under waifu2x. Upscayl's auto tiling is broken on this
    # machine and a custom size works around it, so the size is part of what made the page.
    tile_size: int

    def as_dict(self) -> dict[str, Any]:
        """Return the recipe as plain json-ready values, in a stable key order.

        Returns:
            The settings, keyed by field name.

        """
        return {field: getattr(self, field) for field in sorted(self.__slots__)}

    def as_json(self) -> str:
        """Return the recipe as compact canonical json.

        Returns:
            The settings as a single-line json object with sorted keys.

        """
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def recipe_id(self) -> str:
        """Return a short stable digest of the recipe.

        Only a convenience for comparing two recipes quickly - ``as_dict`` is the
        readable record, and is what gets written out beside the id.

        Returns:
            Twelve hex characters.

        """
        digest = hashlib.blake2s(self.as_json().encode(), digest_size=_RECIPE_ID_LENGTH)
        return digest.hexdigest()[:_RECIPE_ID_LENGTH]

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> UpscaleRecipe:
        """Rebuild a recipe from ``as_dict`` output.

        Args:
            values: A recipe as written to the ledger or a page's png metadata.

        Returns:
            The recipe.

        Raises:
            ValueError: If a field is missing, which means the record was written by a
                different version of this module.

        """
        missing = set(cls.__slots__) - set(values)
        if missing:
            msg = f"Recipe is missing {sorted(missing)} - written by another version?"
            raise ValueError(msg)

        return cls(**{field: values[field] for field in cls.__slots__})


def get_current_recipe(upscaler: Upscaler, scale: int) -> UpscaleRecipe:
    """Return the recipe the upscale would use right now.

    Reads the live constants out of `upscale_image`, so that tuning any of them changes
    the recipe id and schedules the pages made under the old value to be redone.

    Args:
        upscaler: Which backend would run.
        scale: The upscale factor.

    Returns:
        The current recipe.

    """
    is_upscayl = upscaler == Upscaler.UPSCAYL

    return UpscaleRecipe(
        recipe_version=RECIPE_VERSION,
        upscaler=str(upscaler),
        scale=scale,
        model=UPSCAYL_MODEL if is_upscayl else WAIFU2X_MODEL,
        noise_level=NOT_APPLICABLE if is_upscayl else WAIFU2X_NOISE_LEVEL,
        tile_size=UPSCAYL_TILE_SIZE if is_upscayl else NOT_APPLICABLE,
    )
