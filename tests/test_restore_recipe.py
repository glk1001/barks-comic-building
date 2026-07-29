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

import pytest

from barks_comic_building.restore.restore_recipe import (
    RECIPE_VERSION,
    RestoreRecipe,
    get_current_recipe,
)

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

    @pytest.mark.parametrize(
        "field",
        [
            "smooth_threshold",
            "snap_distance",
            "median_blur_aperture",
            "num_posterize_levels",
            "vtracer_params",
            "inpaint_params",
            "smooth_params",
            "recipe_version",
        ],
    )
    def test_id_follows_every_setting(self, recipe: RestoreRecipe, field: str) -> None:
        """No setting may be carried without being hashed.

        One that is not would let a tuning change slip through as already done, which is
        the exact failure the recipe exists to prevent.
        """
        current = getattr(recipe, field)
        changed = f"{current}-changed" if isinstance(current, str) else current + 1
        altered = dataclasses.replace(recipe, **{field: changed})

        assert altered.recipe_id != recipe.recipe_id

    def test_id_is_short_and_hex(self, recipe: RestoreRecipe) -> None:
        assert len(recipe.recipe_id) == RECIPE_ID_LENGTH
        int(recipe.recipe_id, 16)


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
