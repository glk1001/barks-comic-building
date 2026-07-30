"""Tests for the recipe that decides whether an upscayled page is out of date.

The upscale recipe drives a re-run of thousands of pages of GPU work, so it has to follow
every setting that changes the output and nothing else. It also has to keep the two
backends apart: the library was made with Upscayl and the default is now waifu2x, and
tuning one must not invalidate pages made with the other.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from barks_comic_building.restore.upscale_image import Upscaler
from barks_comic_building.restore.upscale_recipe import (
    NOT_APPLICABLE,
    RECIPE_VERSION,
    UpscaleRecipe,
    get_current_recipe,
)

RECIPE_ID_LENGTH = 12
SCALE = 4


@pytest.fixture
def recipe() -> UpscaleRecipe:
    return get_current_recipe(Upscaler.WAIFU2X, SCALE)


class TestRecipeIdentity:
    def test_id_is_stable_across_calls(self, recipe: UpscaleRecipe) -> None:
        assert recipe.recipe_id == get_current_recipe(Upscaler.WAIFU2X, SCALE).recipe_id

    def test_id_follows_the_backend(self, recipe: UpscaleRecipe) -> None:
        """The whole library was made with the other one."""
        assert recipe.recipe_id != get_current_recipe(Upscaler.UPSCAYL, SCALE).recipe_id

    def test_id_follows_the_scale(self, recipe: UpscaleRecipe) -> None:
        assert recipe.recipe_id != get_current_recipe(Upscaler.WAIFU2X, 2).recipe_id

    @pytest.mark.parametrize(
        "field",
        ["upscaler", "scale", "model", "noise_level", "tile_size", "recipe_version"],
    )
    def test_id_follows_every_setting(self, recipe: UpscaleRecipe, field: str) -> None:
        """No setting may be carried without being hashed.

        One that is not would let a tuning change slip through as already done, which is
        the exact failure the recipe exists to prevent.
        """
        current = getattr(recipe, field)
        changed = f"{current}-changed" if isinstance(current, str) else current + 1
        # Dynamic by design, as in test_restore_recipe.py - see the note there.
        # pyrefly: ignore[bad-argument-type]
        altered = dataclasses.replace(recipe, **{field: changed})

        assert altered.recipe_id != recipe.recipe_id

    def test_id_is_short_and_hex(self, recipe: UpscaleRecipe) -> None:
        assert len(recipe.recipe_id) == RECIPE_ID_LENGTH
        int(recipe.recipe_id, 16)


class TestBackendsAreKeptApart:
    """Tuning one backend must not mark the other backend's pages stale."""

    def test_waifu2x_recipe_does_not_carry_the_upscayl_tile_size(
        self, recipe: UpscaleRecipe
    ) -> None:
        assert recipe.tile_size == NOT_APPLICABLE

    def test_upscayl_recipe_does_not_carry_the_waifu2x_noise_level(self) -> None:
        assert get_current_recipe(Upscaler.UPSCAYL, SCALE).noise_level == NOT_APPLICABLE

    def test_each_backend_records_its_own_model(self, recipe: UpscaleRecipe) -> None:
        assert recipe.model != get_current_recipe(Upscaler.UPSCAYL, SCALE).model


class TestRecipeRoundTrip:
    def test_survives_as_dict(self, recipe: UpscaleRecipe) -> None:
        assert UpscaleRecipe.from_dict(recipe.as_dict()) == recipe

    def test_survives_json(self, recipe: UpscaleRecipe) -> None:
        """The form actually written into a page's png metadata."""
        assert UpscaleRecipe.from_dict(json.loads(recipe.as_json())) == recipe

    def test_as_json_is_canonical(self, recipe: UpscaleRecipe) -> None:
        """Two equal recipes must serialise identically, or their ids would differ."""
        assert recipe.as_json() == UpscaleRecipe.from_dict(recipe.as_dict()).as_json()

    def test_as_dict_is_plain_values(self, recipe: UpscaleRecipe) -> None:
        """A reader must not need this package to make sense of a recipe."""
        for value in recipe.as_dict().values():
            assert isinstance(value, (str, int, float, bool))

    def test_from_dict_rejects_a_missing_field(self, recipe: UpscaleRecipe) -> None:
        """Better to refuse than to silently default and call a stale page current."""
        values = recipe.as_dict()
        del values["noise_level"]

        with pytest.raises(ValueError, match="noise_level"):
            UpscaleRecipe.from_dict(values)

    def test_carries_the_version(self, recipe: UpscaleRecipe) -> None:
        assert recipe.recipe_version == RECIPE_VERSION
