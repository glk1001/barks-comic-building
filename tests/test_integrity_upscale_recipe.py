"""Tests that the integrity check holds every upscayled page to the current upscale recipe.

The dependency chain only compares timestamps, so a page upscayled with Upscayl, or with
waifu2x under settings that have since changed, passed the build check as long as it was
older than what was made from it. The recipe id stamped into each upscayled png says what
made it, so the check compares that against the recipe a re-run would use: changing a
waifu2x setting is meant to fail the check until every page has been upscayled again.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from barks_fantagraphics.pages import SrceDependency
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from barks_comic_building.build.comics_integrity import (
    ComicsIntegrityChecker,
    StaleUpscale,
    get_stale_upscale,
    get_upscayled_file_in_chain,
)
from barks_comic_building.restore.upscale_image import UPSCALER_KEY
from barks_comic_building.restore.upscale_state import RECIPE_ID_KEY

if TYPE_CHECKING:
    import pytest

CURRENT_RECIPE_ID = "aaaaaaaaaaaa"
OLD_RECIPE_ID = "bbbbbbbbbbbb"

UPSCAYLED_DIR = Path("/fanta/upscayled/images")
UPSCAYLED_FIXES_DIR = Path("/fanta/upscayled-fixes/images")
RESTORED_DIR = Path("/fanta/restored/images")


def write_png(path: Path, metadata: dict[str, str] | None = None) -> Path:
    """Write a tiny png, optionally carrying BARKS metadata."""
    info = PngInfo()
    for key, value in (metadata or {}).items():
        info.add_text(f"BARKS:{key}", value)

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2)).save(str(path), pnginfo=info)

    return path


def chain(*files: Path) -> list[SrceDependency]:
    return [SrceDependency(file, 1.0, independent=False) for file in files]


class TestFindingTheUpscayledFile:
    def test_the_plain_upscayled_file_is_found(self) -> None:
        upscayled = UPSCAYLED_DIR / "001.png"
        dependencies = chain(RESTORED_DIR / "001.png", upscayled)

        assert get_upscayled_file_in_chain(dependencies, UPSCAYLED_DIR) == upscayled

    def test_a_hand_edited_fixes_file_is_not_graded(self) -> None:
        """It stands in for the upscayled page and carries no recipe of ours."""
        dependencies = chain(RESTORED_DIR / "001.png", UPSCAYLED_FIXES_DIR / "001.png")

        assert get_upscayled_file_in_chain(dependencies, UPSCAYLED_DIR) is None

    def test_a_chain_with_no_upscayled_stage_has_nothing_to_grade(self) -> None:
        """An added-fixes page's chain stops at the restored file."""
        assert get_upscayled_file_in_chain(chain(RESTORED_DIR / "001.png"), UPSCAYLED_DIR) is None


class TestGradingAgainstTheRecipe:
    def test_a_page_made_with_the_current_recipe_passes(self, tmp_path: Path) -> None:
        page = write_png(tmp_path / "001.png", {RECIPE_ID_KEY: CURRENT_RECIPE_ID})

        assert get_stale_upscale(page, CURRENT_RECIPE_ID) is None

    def test_a_page_made_under_older_settings_fails(self, tmp_path: Path) -> None:
        page = write_png(
            tmp_path / "001.png", {RECIPE_ID_KEY: OLD_RECIPE_ID, UPSCALER_KEY: "waifu2x"}
        )

        assert get_stale_upscale(page, CURRENT_RECIPE_ID) == StaleUpscale(
            page, "waifu2x", OLD_RECIPE_ID
        )

    def test_a_page_with_no_recipe_fails_and_names_its_upscaler(self, tmp_path: Path) -> None:
        """The pre-provenance pages: only their backend's model key says what made them."""
        page = write_png(tmp_path / "001.png", {"Upscayl model": "ultramix_balanced"})

        assert get_stale_upscale(page, CURRENT_RECIPE_ID) == StaleUpscale(page, "upscayl", "")

    def test_a_page_with_no_metadata_at_all_fails(self, tmp_path: Path) -> None:
        page = write_png(tmp_path / "001.png")

        assert get_stale_upscale(page, CURRENT_RECIPE_ID) == StaleUpscale(page, "", "")

    def test_a_staged_page_is_graded_through_its_link(self, tmp_path: Path) -> None:
        """A collection's borrowed page is the owning volume's page, read through the link."""
        owner = write_png(tmp_path / "vol22" / "057.png", {RECIPE_ID_KEY: OLD_RECIPE_ID})
        link = tmp_path / "vol1" / "606.png"
        link.parent.mkdir()
        link.symlink_to(owner)

        stale = get_stale_upscale(link, CURRENT_RECIPE_ID)

        assert stale is not None
        assert stale.recipe_id == OLD_RECIPE_ID


class TestTheReport:
    def test_findings_are_an_error(self) -> None:
        errors = ComicsIntegrityChecker.make_out_of_date_errors("Fake Title")
        errors.stale_upscayled_files.append(StaleUpscale(UPSCAYLED_DIR / "001.png", "", ""))

        assert errors.file_findings
        assert errors.is_error

    def test_pages_are_grouped_by_what_made_them(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A settings change puts every page here at once, so the report must not list them."""
        errors = ComicsIntegrityChecker.make_out_of_date_errors("Fake Title")
        errors.current_upscale_recipe = f'"{CURRENT_RECIPE_ID}" (waifu2x)'
        errors.stale_upscayled_files.extend(
            [StaleUpscale(UPSCAYLED_DIR / f"{n:03}.png", "upscayl", "") for n in range(1, 4)]
            + [StaleUpscale(UPSCAYLED_DIR / "004.png", "waifu2x", OLD_RECIPE_ID)]
        )

        ComicsIntegrityChecker.print_out_of_date_or_missing_errors(errors)
        out = capsys.readouterr().out

        expected = "4 upscayled page(s) were not made with the current upscale recipe"
        assert f'{expected} "{CURRENT_RECIPE_ID}" (waifu2x):' in out
        assert "3 made by upscayl, no recipe recorded." in out
        assert f'1 made by waifu2x, recipe "{OLD_RECIPE_ID}".' in out
        assert "001.png" not in out
        assert "4 upscayled pages not at the current recipe" in out
