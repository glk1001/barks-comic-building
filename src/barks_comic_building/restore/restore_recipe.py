"""The set of settings that decide what a restored page comes out looking like.

A restored page is only as good as the tuning that made it, and that tuning changes: the
smoothing threshold, whether flat colours are snapped back to the source palette, how the
line art is traced. When any of it moves, every page made before the move is out of date,
and the library is large enough that working out which pages those are by hand is not
practical.

So the pipeline records the settings it used, both alongside the page in its png metadata
and in the run ledger, and compares them on the next run. A page whose recipe matches the
current one is finished; anything else is redone. Adjusting a constant in one of the step
modules is therefore all it takes to schedule the re-run it implies - nothing has to be
deleted by hand, and nothing has to be remembered.

The recipe is written out in full rather than only as a digest, so that a later reader can
see what a page was actually made with instead of only whether it differs from today.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from barks_comic_building.restore import palette_snap
from barks_comic_building.restore.inpaint import GMIC_INPAINT_MATCHPATCH_PARAMS
from barks_comic_building.restore.remove_alias_artifacts import (
    ADAPTIVE_THRESHOLD_BLOCK_SIZE,
    ADAPTIVE_THRESHOLD_CONST_SUBTRACT,
    MEDIAN_BLUR_APERTURE_SIZE,
)
from barks_comic_building.restore.remove_colors import NUM_POSTERIZE_LEVELS
from barks_comic_building.restore.smooth_image import (
    GMIC_SMOOTH_ANISOTROPIC_PARAMS,
    SMOOTH_THRESHOLD,
)
from barks_comic_building.restore.vtracer_to_svg import VTRACER_PARAMS

# Bumped when the shape of a recipe changes in a way that makes old ids incomparable.
# Part of the hashed content, so bumping it invalidates every page.
RECIPE_VERSION = 1

_RECIPE_ID_LENGTH = 12


@dataclass(frozen=True, slots=True)
class RestoreRecipe:
    """Every setting that changes what a restored page looks like.

    Deliberately flat and made of plain values, so that ``as_dict`` round trips through
    json and a reader needs nothing from this package to make sense of it.
    """

    recipe_version: int
    scale: int

    # Removing the jpeg artifacts.
    median_blur_aperture: int
    adaptive_threshold_block: int
    adaptive_threshold_subtract: int

    # Isolating the ink.
    num_posterize_levels: int

    # Smoothing it and turning it back into a mask.
    smooth_params: str
    smooth_threshold: int

    # Tracing it.
    vtracer_params: str

    # Filling the ink back out of the colour layer.
    inpaint_params: str

    # Putting the flat colours back on the source's palette.
    do_palette_snap: bool
    snap_distance: int
    merge_distance: int
    min_palette_share: float
    srce_flat_kernel: int
    srce_flat_max: int
    dest_flat_kernel: int
    dest_flat_max: int
    ink_max_luminance: int

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
    def from_dict(cls, values: dict[str, Any]) -> RestoreRecipe:
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


def get_current_recipe(scale: int, *, do_palette_snap: bool) -> RestoreRecipe:
    """Return the recipe the pipeline would use right now.

    Reads the live constants out of the step modules, so that tuning any of them changes
    the recipe id and schedules the pages made under the old value to be redone.

    Args:
        scale: The upscale factor the restore runs at.
        do_palette_snap: Whether flat colours get snapped to the source palette.

    Returns:
        The current recipe.

    """
    return RestoreRecipe(
        recipe_version=RECIPE_VERSION,
        scale=scale,
        median_blur_aperture=MEDIAN_BLUR_APERTURE_SIZE,
        adaptive_threshold_block=ADAPTIVE_THRESHOLD_BLOCK_SIZE,
        adaptive_threshold_subtract=ADAPTIVE_THRESHOLD_CONST_SUBTRACT,
        num_posterize_levels=NUM_POSTERIZE_LEVELS,
        smooth_params=GMIC_SMOOTH_ANISOTROPIC_PARAMS,
        smooth_threshold=SMOOTH_THRESHOLD,
        vtracer_params=json.dumps(VTRACER_PARAMS, sort_keys=True, separators=(",", ":")),
        inpaint_params=GMIC_INPAINT_MATCHPATCH_PARAMS,
        do_palette_snap=do_palette_snap,
        snap_distance=palette_snap.SNAP_DISTANCE,
        merge_distance=palette_snap.MERGE_DISTANCE,
        min_palette_share=palette_snap.MIN_PALETTE_SHARE,
        srce_flat_kernel=palette_snap.SRCE_FLAT_KERNEL,
        srce_flat_max=palette_snap.SRCE_FLAT_MAX,
        dest_flat_kernel=palette_snap.DEST_FLAT_KERNEL,
        dest_flat_max=palette_snap.DEST_FLAT_MAX,
        ink_max_luminance=palette_snap.INK_MAX_LUMINANCE,
    )
