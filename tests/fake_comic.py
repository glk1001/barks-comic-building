"""A title made of files in a temporary directory, for tests of the page walks and runs.

The restore and the upscale ask a comic for lists of files and nothing else, so a stand-in
that hands back paths under a temporary directory is all it takes to run them against
pages in any state, without the comics database or the library.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from barks_fantagraphics.comic_book import ModifiedType
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from barks_comic_building.restore.page_state import RECIPE_ID_KEY, get_ink_mask_file
from barks_comic_building.restore.restore_recipe import get_current_recipe
from barks_comic_building.restore.upscale_image import DEFAULT_UPSCALER, LIBRARY_SCALE
from barks_comic_building.restore.upscale_recipe import (
    get_current_recipe as get_current_upscale_recipe,
)
from barks_comic_building.restore.upscale_state import RECIPE_ID_KEY as UPSCALE_RECIPE_ID_KEY
from barks_comic_building.restore.upscale_state import UPSCALE_DATE_KEY

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comics_consts import PageType
    from barks_fantagraphics.comics_database import ComicsDatabase

TITLE = "Lost in the Andes!"
VOLUME = 7

RESTORE_RECIPE = get_current_recipe(LIBRARY_SCALE, do_palette_snap=True)
RESTORE_RECIPE_ID = RESTORE_RECIPE.recipe_id
UPSCALE_RECIPE = get_current_upscale_recipe(DEFAULT_UPSCALER, LIBRARY_SCALE)
UPSCALE_RECIPE_ID = UPSCALE_RECIPE.recipe_id
OLD_RECIPE_ID = "bbbbbbbbbbbb"


def write_png(path: Path, metadata: dict[str, str] | None = None) -> Path:
    """Write a tiny png, optionally carrying BARKS metadata."""
    info = PngInfo()
    for key, value in (metadata or {}).items():
        info.add_text(f"BARKS:{key}", value)

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2)).save(str(path), pnginfo=info)

    return path


class FakeComic:
    """A title made of files in a temporary directory."""

    def __init__(self, tmp_path: Path, pages: list[str]) -> None:
        self.root = tmp_path
        self.pages = pages
        self.fixes_pages: set[str] = set()
        self.hand_restored_pages: set[str] = set()

    def srce(self, page: str) -> Path:
        return self.root / "original" / f"{page}.jpg"

    def upscayl(self, page: str) -> Path:
        return self.root / "upscayled" / f"{page}.png"

    def restored(self, page: str) -> Path:
        return self.root / "restored" / f"{page}.png"

    def restored_4x(self, page: str) -> Path:
        return self.root / "restored-upscayled" / f"{page}.png"

    def svg(self, page: str) -> Path:
        return self.root / "restored-svg" / f"{page}.svg"

    # ---- what the walks ask for

    def get_final_srce_original_story_files(
        self, _page_types: list[PageType]
    ) -> list[tuple[Path, ModifiedType]]:
        return [(self.srce(page), ModifiedType.ORIGINAL) for page in self.pages]

    def get_final_srce_upscayled_story_files(
        self, _page_types: list[PageType]
    ) -> list[tuple[Path, ModifiedType]]:
        return [
            (
                self.upscayl(page),
                ModifiedType.MODIFIED if page in self.fixes_pages else ModifiedType.ORIGINAL,
            )
            for page in self.pages
        ]

    def get_srce_restored_story_files(self, _page_types: list[PageType]) -> list[Path]:
        return [self.restored(page) for page in self.pages]

    def get_srce_restored_upscayled_story_files(self, _page_types: list[PageType]) -> list[Path]:
        return [self.restored_4x(page) for page in self.pages]

    def get_srce_restored_svg_story_files(self, _page_types: list[PageType]) -> list[Path]:
        return [self.svg(page) for page in self.pages]

    def is_hand_restored(self, page_num: str) -> bool:
        return page_num in self.hand_restored_pages

    # ---- putting pages in the states the tests want

    def write_srce(self, page: str) -> None:
        write_png(self.srce(page))

    def write_upscayled(self, page: str, recipe_id: str = UPSCALE_RECIPE_ID) -> None:
        self.write_srce(page)
        write_png(
            self.upscayl(page),
            {UPSCALE_RECIPE_ID_KEY: recipe_id, UPSCALE_DATE_KEY: "2026-11-02T09:30:00+11:00"},
        )

    def write_restored(self, page: str, recipe_id: str = RESTORE_RECIPE_ID) -> None:
        self.write_upscayled(page)
        write_png(self.restored(page), {RECIPE_ID_KEY: recipe_id})
        write_png(self.restored_4x(page))
        self.svg(page).parent.mkdir(parents=True, exist_ok=True)
        self.svg(page).write_text("<svg/>")
        write_png(get_ink_mask_file(self.svg(page)))


class FakeDatabase:
    """As much of the comics database as a run asks for: one title."""

    def __init__(self, comic: FakeComic) -> None:
        self.comic = comic

    def get_comic_book(self, _title: str) -> FakeComic:
        return self.comic

    def get_fanta_volume_int(self, _title: str) -> int:
        return VOLUME


def as_database(comic: FakeComic) -> ComicsDatabase:
    return cast("ComicsDatabase", FakeDatabase(comic))
