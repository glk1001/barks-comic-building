"""Tests that a staged one-pager is graded in the volume it really belongs to.

In "All One-Pagers" every page is an ADDED page, so its dependency chain stops at the
restored file and nothing below it - the svg, the upscale, the scan, the upscale recipe -
is graded there. A one-pager that belongs to no title is not graded at home either,
because the per-volume walk goes title by title. Vol 20 page 036 ("The Big Bobber") sat
on a pre-recipe Upscayl upscale for a year that way, with the check passing.

So the check grades a staged page's chain out of its home volume's real files. Not the
collection's links: a link's timestamp is its own and moves on every restage.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

import pytest
from barks_fantagraphics.comics_consts import IMAGES_SUBDIR
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from barks_comic_building.build import stage_one_pagers
from barks_comic_building.build.collection_staging import members_by_collection_page
from barks_comic_building.build.comics_integrity import (
    ComicsIntegrityChecker,
    HomeChain,
    StaleUpscale,
    check_home_chain,
    get_home_chain,
)
from barks_comic_building.restore.upscale_state import RECIPE_ID_KEY

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.barks_titles import Titles
    from barks_fantagraphics.comics_database import ComicsDatabase

CURRENT_RECIPE_ID = "aaaaaaaaaaaa"

VOLUME = 20
PAGE = "036"


class FakeComicsDatabase:
    """The home volume's trees, rooted under `tmp_path`, in the real database's shapes."""

    def __init__(self, tmp_path: Path) -> None:
        self._root = tmp_path

    def _volume_images(self, tree: str, volume: int) -> Path:
        return self._root / tree / f"volume-{volume:02d}" / IMAGES_SUBDIR

    def get_fantagraphics_volume_image_dir(self, volume_num: int) -> Path:
        return self._volume_images("original", volume_num)

    def get_fantagraphics_fixes_volume_image_dir(self, volume_num: int) -> Path:
        return self._volume_images("fixes", volume_num)

    def get_fantagraphics_upscayled_volume_image_dir(self, volume_num: int) -> Path:
        return self._volume_images("upscayled", volume_num)

    def get_fantagraphics_upscayled_fixes_volume_image_dir(self, volume_num: int) -> Path:
        return self._volume_images("upscayled-fixes", volume_num)

    def get_fantagraphics_restored_volume_image_dir(self, volume_num: int) -> Path:
        return self._volume_images("restored", volume_num)

    def get_fantagraphics_restored_upscayled_volume_image_dir(self, volume_num: int) -> Path:
        return self._volume_images("restored-upscayled", volume_num)

    def get_fantagraphics_restored_svg_volume_image_dir(self, volume_num: int) -> Path:
        return self._volume_images("restored-svg", volume_num)

    def get_fantagraphics_panel_segments_volume_dir(self, volume_num: int) -> Path:
        return self._root / "panel-segments" / f"volume-{volume_num:02d}"


def as_database(fake: FakeComicsDatabase) -> ComicsDatabase:
    return cast("ComicsDatabase", fake)


def write_file(path: Path, mtime: float, metadata: dict[str, str] | None = None) -> Path:
    """Write a tiny png (or an empty file, for a non-png) and date it `mtime`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".png":
        info = PngInfo()
        for key, value in (metadata or {}).items():
            info.add_text(f"BARKS:{key}", value)
        Image.new("RGB", (2, 2)).save(str(path), pnginfo=info)
    else:
        path.touch()
    os.utime(path, (mtime, mtime))

    return path


def write_home_page(
    database: FakeComicsDatabase,
    *,
    upscale_recipe: str = CURRENT_RECIPE_ID,
    upscayled_mtime: float = 2000.0,
) -> None:
    """Write a fully processed home page, each stage newer than the one it came from."""
    write_file(database.get_fantagraphics_volume_image_dir(VOLUME) / f"{PAGE}.jpg", 1000.0)
    write_file(
        database.get_fantagraphics_upscayled_volume_image_dir(VOLUME) / f"{PAGE}.png",
        upscayled_mtime,
        {RECIPE_ID_KEY: upscale_recipe},
    )
    write_file(
        database.get_fantagraphics_restored_svg_volume_image_dir(VOLUME) / f"{PAGE}.svg", 3000.0
    )
    write_file(
        database.get_fantagraphics_restored_upscayled_volume_image_dir(VOLUME) / f"{PAGE}.png",
        4000.0,
    )
    write_file(database.get_fantagraphics_restored_volume_image_dir(VOLUME) / f"{PAGE}.png", 5000.0)


def grade(home_chain: HomeChain) -> tuple[list[tuple[Path, Path]], list[StaleUpscale]]:
    errors = ComicsIntegrityChecker.make_out_of_date_errors("All One-Pagers")
    check_home_chain(home_chain, errors, CURRENT_RECIPE_ID)

    return errors.srce_and_dest_files_out_of_date, errors.stale_upscayled_files


@pytest.fixture
def database(tmp_path: Path) -> FakeComicsDatabase:
    return FakeComicsDatabase(tmp_path)


class TestHomePages:
    def test_members_are_numbered_from_the_base_in_table_order(self) -> None:
        members = cast("list[tuple[Titles, int, int]]", [("a", 20, 36), ("b", 7, 241)])

        assert members_by_collection_page(members, 500) == {500: members[0], 501: members[1]}

    def test_each_home_page_is_the_one_its_restored_slot_is_staged_from(
        self, database: FakeComicsDatabase
    ) -> None:
        """The check must grade the page the stager filled, against the real table."""
        home_pages = stage_one_pagers.get_home_pages()
        links_by_title = stage_one_pagers.get_staged_links_by_title(as_database(database))
        restored_root = database.get_fantagraphics_restored_volume_image_dir(0).parent.parent

        staged = {
            link.stem: source
            for links in links_by_title.values()
            for link, source in links
            if link.is_relative_to(restored_root)
        }

        assert staged.keys() == home_pages.keys()
        for collection_page, (volume, page) in home_pages.items():
            expected = database.get_fantagraphics_restored_volume_image_dir(volume) / f"{page}.png"
            assert staged[collection_page] == expected


class TestTheHomeChain:
    def test_the_stages_run_newest_first(self, database: FakeComicsDatabase) -> None:
        write_home_page(database)

        home_chain = get_home_chain(as_database(database), VOLUME, PAGE)

        assert [dependency.file for dependency in home_chain.dependencies] == [
            database.get_fantagraphics_restored_upscayled_volume_image_dir(VOLUME) / f"{PAGE}.png",
            database.get_fantagraphics_restored_svg_volume_image_dir(VOLUME) / f"{PAGE}.svg",
            database.get_fantagraphics_upscayled_volume_image_dir(VOLUME) / f"{PAGE}.png",
            database.get_fantagraphics_volume_image_dir(VOLUME) / f"{PAGE}.jpg",
        ]
        assert home_chain.restored_file == (
            database.get_fantagraphics_restored_volume_image_dir(VOLUME) / f"{PAGE}.png"
        )

    def test_a_stage_not_on_disk_has_the_missing_sentinel(
        self, database: FakeComicsDatabase
    ) -> None:
        home_chain = get_home_chain(as_database(database), VOLUME, PAGE)

        assert all(dependency.timestamp == -1 for dependency in home_chain.dependencies)

    def test_the_scan_is_taken_from_the_fixes_tree_when_it_has_one(
        self, database: FakeComicsDatabase
    ) -> None:
        """As the stager and the build take it - an added page has no original at all."""
        fix = write_file(
            database.get_fantagraphics_fixes_volume_image_dir(VOLUME) / f"{PAGE}.jpg", 1.0
        )

        home_chain = get_home_chain(as_database(database), VOLUME, PAGE)

        assert home_chain.dependencies[-1].file == fix

    def test_a_hand_edited_upscayl_is_not_graded_against_the_recipe(
        self, database: FakeComicsDatabase
    ) -> None:
        fix = write_file(
            database.get_fantagraphics_upscayled_fixes_volume_image_dir(VOLUME) / f"{PAGE}.png", 1.0
        )

        home_chain = get_home_chain(as_database(database), VOLUME, PAGE)

        assert home_chain.dependencies[2].file == fix
        assert home_chain.upscayled_file is None

    def test_a_hand_restored_page_is_marked(self, database: FakeComicsDatabase) -> None:
        assert get_home_chain(as_database(database), 4, "227").is_hand_restored
        assert not get_home_chain(as_database(database), VOLUME, PAGE).is_hand_restored


class TestGradingTheHomeChain:
    def test_a_current_page_passes(self, database: FakeComicsDatabase) -> None:
        write_home_page(database)

        assert grade(get_home_chain(as_database(database), VOLUME, PAGE)) == ([], [])

    def test_an_upscale_off_the_current_recipe_is_found(self, database: FakeComicsDatabase) -> None:
        """The Vol 20 page 036 case: a pre-recipe upscale, otherwise in order."""
        write_home_page(database, upscale_recipe="")

        stale_pairs, stale_upscales = grade(get_home_chain(as_database(database), VOLUME, PAGE))

        assert stale_pairs == []
        assert [stale.file.name for stale in stale_upscales] == [f"{PAGE}.png"]

    def test_an_upscale_newer_than_its_restore_is_found(self, database: FakeComicsDatabase) -> None:
        """The Vol 7 page 241 case: upscayled again, never restored again."""
        write_home_page(database, upscayled_mtime=3500.0)
        home_chain = get_home_chain(as_database(database), VOLUME, PAGE)

        stale_pairs, _stale_upscales = grade(home_chain)

        upscayled, svg = home_chain.dependencies[2].file, home_chain.dependencies[1].file
        assert stale_pairs == [(upscayled, svg)]

    def test_a_hand_restored_page_is_not_held_to_the_recipe(
        self, database: FakeComicsDatabase
    ) -> None:
        write_home_page(database, upscale_recipe="")
        home_chain = get_home_chain(as_database(database), VOLUME, PAGE)
        hand_restored = HomeChain(
            home_chain.restored_file,
            home_chain.dependencies,
            home_chain.upscayled_file,
            is_hand_restored=True,
        )

        assert grade(hand_restored) == ([], [])

    def test_a_page_with_no_home_restored_file_is_left_alone(
        self, database: FakeComicsDatabase
    ) -> None:
        """Its staged link is dangling, which the staged-links check reports."""
        write_home_page(database, upscale_recipe="")
        home_chain = get_home_chain(as_database(database), VOLUME, PAGE)
        home_chain.restored_file.unlink()

        assert grade(home_chain) == ([], [])
