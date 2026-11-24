"""Tests for the recipe that decides whether a restored page is out of date.

The recipe id is what a five hundred hour re-run is driven from: a page whose id matches
the current one is left alone, and one whose id differs is done again. So the properties
that matter are that the id follows every setting that changes the output, that it does
not follow anything else, and that a recipe survives the round trip through the ledger and
the page's own png metadata - a recipe that cannot be read back is a page that can never
be shown to be current.
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

import pytest

from barks_comic_building.restore import palette_snap, restore_recipe
from barks_comic_building.restore.restore_recipe import (
    RECIPE_VERSION,
    RestoreRecipe,
    get_current_recipe,
)

if TYPE_CHECKING:
    from types import ModuleType

RECIPE_ID_LENGTH = 12


@pytest.fixture
def recipe() -> RestoreRecipe:
    return get_current_recipe(4, do_palette_snap=True)


class TestRecipeIdentity:
    def test_id_is_stable_across_calls(self, recipe: RestoreRecipe) -> None:
        assert recipe.recipe_id == get_current_recipe(4, do_palette_snap=True).recipe_id

    def test_id_follows_the_snap_setting(self, recipe: RestoreRecipe) -> None:
        assert recipe.recipe_id != get_current_recipe(4, do_palette_snap=False).recipe_id

    def test_id_follows_the_scale(self, recipe: RestoreRecipe) -> None:
        assert recipe.recipe_id != get_current_recipe(2, do_palette_snap=True).recipe_id

    @pytest.mark.parametrize("field", [f.name for f in dataclasses.fields(RestoreRecipe)])
    def test_id_follows_every_setting(self, recipe: RestoreRecipe, field: str) -> None:
        """No setting may be carried without being hashed.

        One that is not would let a tuning change slip through as already done, which is
        the exact failure the recipe exists to prevent.

        Taken from the recipe's own fields rather than a list kept here. A list is what
        this used to have, eight names long against nineteen fields, under a comment
        saying it covered settings added later.
        """
        current = getattr(recipe, field)
        if isinstance(current, bool):
            changed = not current
        elif isinstance(current, str):
            changed = f"{current}-changed"
        else:
            changed = current + 1
        # The field name is only known at runtime, so pyrefly checks the unpacked dict
        # against every field of the recipe and objects to all of them. Being dynamic is
        # the point of the test - it is what makes it cover settings added later.
        # pyrefly: ignore[bad-argument-type]
        altered = dataclasses.replace(recipe, **{field: changed})

        assert altered.recipe_id != recipe.recipe_id

    def test_id_is_short_and_hex(self, recipe: RestoreRecipe) -> None:
        assert len(recipe.recipe_id) == RECIPE_ID_LENGTH
        int(recipe.recipe_id, 16)


# Where each setting of the recipe is read from: the name it is tuned under, and the
# module `get_current_recipe` looks it up in. `scale` and `do_palette_snap` are arguments
# rather than constants, and are covered above.
_STEP_CONSTANTS = [
    (restore_recipe, "RECIPE_VERSION"),
    (restore_recipe, "MEDIAN_BLUR_APERTURE_SIZE"),
    (restore_recipe, "ADAPTIVE_THRESHOLD_BLOCK_SIZE"),
    (restore_recipe, "ADAPTIVE_THRESHOLD_CONST_SUBTRACT"),
    (restore_recipe, "NUM_POSTERIZE_LEVELS"),
    (restore_recipe, "GMIC_SMOOTH_ANISOTROPIC_PARAMS"),
    (restore_recipe, "SMOOTH_THRESHOLD"),
    (restore_recipe, "VTRACER_PARAMS"),
    (restore_recipe, "GMIC_INPAINT_MATCHPATCH_PARAMS"),
    (palette_snap, "SNAP_DISTANCE"),
    (palette_snap, "MERGE_DISTANCE"),
    (palette_snap, "MIN_PALETTE_SHARE"),
    (palette_snap, "SRCE_FLAT_KERNEL"),
    (palette_snap, "SRCE_FLAT_MAX"),
    (palette_snap, "DEST_FLAT_KERNEL"),
    (palette_snap, "DEST_FLAT_MAX"),
    (palette_snap, "INK_MAX_LUMINANCE"),
]
_NUM_ARGUMENT_FIELDS = 2


class TestTheRecipeReadsTheLiveSettings:
    """Tuning a step constant is all it should take to schedule a re-run.

    The test above shows a changed field changes the id. It cannot show that a field is
    wired to the constant it claims to record - one read from the wrong place, or from
    nowhere, would hash perfectly well and never move.
    """

    @pytest.mark.parametrize(
        ("module", "name"), _STEP_CONSTANTS, ids=[name for _, name in _STEP_CONSTANTS]
    )
    def test_changing_a_step_constant_changes_the_id(
        self,
        recipe: RestoreRecipe,
        monkeypatch: pytest.MonkeyPatch,
        module: ModuleType,
        name: str,
    ) -> None:
        current = getattr(module, name)
        if isinstance(current, dict):
            changed = {**current, "changed": True}
        elif isinstance(current, str):
            changed = f"{current}-changed"
        else:
            changed = current + 1
        monkeypatch.setattr(module, name, changed)

        assert get_current_recipe(4, do_palette_snap=True).recipe_id != recipe.recipe_id

    def test_every_field_has_a_constant_listed_here(self) -> None:
        """So that a field added to the recipe has to be added to the list above."""
        num_fields = len(dataclasses.fields(RestoreRecipe))

        assert len(_STEP_CONSTANTS) + _NUM_ARGUMENT_FIELDS == num_fields


class TestRecipeRoundTrip:
    def test_survives_as_dict(self, recipe: RestoreRecipe) -> None:
        assert RestoreRecipe.from_dict(recipe.as_dict()) == recipe

    def test_survives_json(self, recipe: RestoreRecipe) -> None:
        """The form actually written into a page's png metadata."""
        assert RestoreRecipe.from_dict(json.loads(recipe.as_json())) == recipe

    def test_as_json_is_canonical(self, recipe: RestoreRecipe) -> None:
        """Two equal recipes must serialise identically, or their ids would differ."""
        assert recipe.as_json() == RestoreRecipe.from_dict(recipe.as_dict()).as_json()

    def test_as_dict_is_plain_values(self, recipe: RestoreRecipe) -> None:
        """A reader must not need this package to make sense of a recipe."""
        for value in recipe.as_dict().values():
            assert isinstance(value, (str, int, float, bool))

    def test_from_dict_rejects_a_missing_field(self, recipe: RestoreRecipe) -> None:
        """Better to refuse than to silently default and call a stale page current."""
        values = recipe.as_dict()
        del values["smooth_threshold"]

        with pytest.raises(ValueError, match="smooth_threshold"):
            RestoreRecipe.from_dict(values)

    def test_carries_the_version(self, recipe: RestoreRecipe) -> None:
        assert recipe.recipe_version == RECIPE_VERSION
