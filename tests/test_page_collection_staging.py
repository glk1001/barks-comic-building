"""Tests for how the synthetic collections' pages are staged out of other volumes.

"All Covers" and "All One-Pagers" are not scanned books. Each is assembled by symlinking
one page out of some other volume into a collection volume, numbered `base + index` over
the located members in table order.

That indexing is the whole risk, and it fails silently. Insert a member into the middle
of `COVER_LOCATIONS` or `ONE_PAGER_LOCATIONS` and every later member's collection page
shifts by one; skip the restage and the on-disk links stay attached to the old numbers.
Nothing is missing and nothing is stale - the built cbz simply shows the wrong gag under
each page. So the numbering is pinned against the real location tables here, and the
integrity gate that catches a stale link is tested separately in
`test_staged_collection_links.py`.

The rest is the staging mechanics: which source a page is taken from when a volume has
both an original and a fixed scan, and what `stage` does to links that already exist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from barks_fantagraphics.barks_covers import (
    COVER_COLLECTION_PAGE_BASE,
    get_cover_location,
    get_cover_title,
    get_located_covers,
)
from barks_fantagraphics.comic_book_info import (
    ONE_PAGER_COLLECTION_PAGE_BASE,
    ONE_PAGER_LOCATIONS,
    get_located_one_pagers,
)
from barks_fantagraphics.comics_consts import IMAGES_SUBDIR

from barks_comic_building.build import stage_covers, stage_one_pagers
from barks_comic_building.build.collection_sources import (
    original_scan_source,
    superseded_links,
)

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comics_database import ComicsDatabase

# A cover is staged from two files: the original scan and its upscayled image. A
# one-pager also has a restored image, a restored-svg pair, and panel segments.
COVER_ARTIFACTS = 2
ONE_PAGER_ARTIFACTS = 6

JPG = ".jpg"
PNG = ".png"
SVG = ".svg"
JSON = ".json"


class FakeComicsDatabase:
    """The six artifact directories the stagers ask for, rooted under `tmp_path`.

    Mirrors the real database's path shapes rather than inventing simpler ones: the five
    image trees end in the images subdirectory and the panel-segments tree does not, so a
    staged path that loses or gains that level shows up here.
    """

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

    def get_fantagraphics_restored_svg_volume_image_dir(self, volume_num: int) -> Path:
        return self._volume_images("restored-svg", volume_num)

    def get_fantagraphics_panel_segments_volume_dir(self, volume_num: int) -> Path:
        # Deliberately not under the images subdirectory, as in the real database.
        return self._root / "panel-segments" / f"volume-{volume_num:02d}"


def as_database(fake: FakeComicsDatabase) -> ComicsDatabase:
    """Present a `FakeComicsDatabase` as the database the stagers are typed against."""
    return cast("ComicsDatabase", fake)


def touch(path: Path) -> Path:
    """Create an empty file, making its parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()

    return path


@pytest.fixture
def database(tmp_path: Path) -> FakeComicsDatabase:
    return FakeComicsDatabase(tmp_path)


class TestCoverCollectionNumbering:
    """Each located cover claims collection page `base + index`, in table order."""

    def test_the_first_located_cover_takes_the_base_page(
        self, database: FakeComicsDatabase
    ) -> None:
        links_by_title = stage_covers.get_staged_links_by_title(as_database(database))
        first_title = get_cover_title(get_located_covers()[0])

        stems = {link.name.split(".")[0] for link, _source in links_by_title[first_title]}

        assert stems == {f"{COVER_COLLECTION_PAGE_BASE:03d}"}

    def test_every_cover_takes_its_own_index(self, database: FakeComicsDatabase) -> None:
        # The assertion the silent page shift would break: member i is page base + i, for
        # every located cover, against the real table.
        links_by_title = stage_covers.get_staged_links_by_title(as_database(database))

        for i, cover in enumerate(get_located_covers()):
            links = links_by_title[get_cover_title(cover)]
            expected = f"{COVER_COLLECTION_PAGE_BASE + i:03d}"

            assert {link.name.split(".")[0] for link, _source in links} == {expected}

    def test_a_cover_is_staged_from_two_artifacts(self, database: FakeComicsDatabase) -> None:
        # Covers are built full-page from the upscayled scan, never restored or
        # panel-processed, so only the original and its upscayled image are worth staging.
        links_by_title = stage_covers.get_staged_links_by_title(as_database(database))
        first_title = get_cover_title(get_located_covers()[0])

        assert len(links_by_title[first_title]) == COVER_ARTIFACTS

    def test_every_located_cover_is_staged(self, database: FakeComicsDatabase) -> None:
        links_by_title = stage_covers.get_staged_links_by_title(as_database(database))

        assert len(links_by_title) == len(get_located_covers())

    def test_the_flat_list_holds_every_candidate(self, database: FakeComicsDatabase) -> None:
        links = stage_covers.get_staged_links(as_database(database))

        assert len(links) == len(get_located_covers()) * COVER_ARTIFACTS

    def test_each_cover_link_is_taken_from_its_own_volume_and_page(
        self, database: FakeComicsDatabase
    ) -> None:
        # The other half of the mapping: the collection page is `base + i`, but the
        # source page is whatever the location table says, in whichever volume.
        links_by_title = stage_covers.get_staged_links_by_title(as_database(database))
        cover = get_located_covers()[0]
        location = get_cover_location(cover)
        assert location is not None
        volume, page = location

        for _link, source in links_by_title[get_cover_title(cover)]:
            assert f"volume-{volume:02d}" in source.parts
            assert source.name.startswith(f"{page:03d}")

    def test_each_cover_artifact_is_staged_into_its_own_tree(
        self, database: FakeComicsDatabase
    ) -> None:
        # Counting the artifacts and checking their page stems says nothing about which
        # of the trees each one lands in, and a slot wired to the wrong tree is invisible
        # until the build reads a file that is not there. Pin both ends of every pair.
        cover = get_located_covers()[0]
        location = get_cover_location(cover)
        assert location is not None
        volume, page = location
        src = f"{page:03d}"
        dst = f"{COVER_COLLECTION_PAGE_BASE:03d}"
        collection = stage_covers.COLLECTION_VOLUME

        links = stage_covers.get_staged_links_by_title(as_database(database))[
            get_cover_title(cover)
        ]

        assert links == [
            (
                database.get_fantagraphics_fixes_volume_image_dir(collection) / f"{dst}{JPG}",
                database.get_fantagraphics_volume_image_dir(volume) / f"{src}{JPG}",
            ),
            (
                database.get_fantagraphics_upscayled_volume_image_dir(collection) / f"{dst}{PNG}",
                database.get_fantagraphics_upscayled_volume_image_dir(volume) / f"{src}{PNG}",
            ),
        ]


class TestOnePagerCollectionNumbering:
    def test_the_first_located_one_pager_takes_the_base_page(
        self, database: FakeComicsDatabase
    ) -> None:
        links_by_title = stage_one_pagers.get_staged_links_by_title(as_database(database))
        first_title = get_located_one_pagers()[0]

        stems = {link.name.split(".")[0] for link, _source in links_by_title[first_title]}

        assert stems == {f"{ONE_PAGER_COLLECTION_PAGE_BASE:03d}"}

    def test_every_one_pager_takes_its_own_index(self, database: FakeComicsDatabase) -> None:
        links_by_title = stage_one_pagers.get_staged_links_by_title(as_database(database))

        for i, title in enumerate(get_located_one_pagers()):
            expected = f"{ONE_PAGER_COLLECTION_PAGE_BASE + i:03d}"

            assert {link.name.split(".")[0] for link, _source in links_by_title[title]} == {
                expected
            }

    def test_a_one_pager_is_staged_from_six_artifacts(self, database: FakeComicsDatabase) -> None:
        links_by_title = stage_one_pagers.get_staged_links_by_title(as_database(database))
        first_title = get_located_one_pagers()[0]

        assert len(links_by_title[first_title]) == ONE_PAGER_ARTIFACTS

    def test_each_link_is_taken_from_its_own_volume_and_page(
        self, database: FakeComicsDatabase
    ) -> None:
        # The other half of the mapping: the collection page is `base + i`, but the
        # source page is whatever the location table says, in whichever volume.
        links_by_title = stage_one_pagers.get_staged_links_by_title(as_database(database))
        title = get_located_one_pagers()[0]
        volume, page, _issue_page = ONE_PAGER_LOCATIONS[title]

        for _link, source in links_by_title[title]:
            assert f"volume-{volume:02d}" in source.parts or "panel-segments" in source.parts
            assert source.name.startswith(f"{page:03d}")

    def test_the_svg_pair_keeps_the_page_stem(self, database: FakeComicsDatabase) -> None:
        # `.svg` and `.svg.png` both belong to page NNN, so a link named "NNN.svg.png"
        # must not end up stemmed as "NNN.svg".
        links_by_title = stage_one_pagers.get_staged_links_by_title(as_database(database))
        title = get_located_one_pagers()[0]
        expected = f"{ONE_PAGER_COLLECTION_PAGE_BASE:03d}"

        names = {link.name for link, _source in links_by_title[title]}

        assert f"{expected}.svg" in names
        assert f"{expected}.svg{PNG}" in names

    def test_each_one_pager_artifact_is_staged_into_its_own_tree(
        self, database: FakeComicsDatabase
    ) -> None:
        # Six artifacts across five trees, and nothing above pins which tree each lands
        # in - swapping two dest dirs kept every other test in this file passing. The
        # panel-segments pair is the one that must *not* gain the images subdir.
        title = get_located_one_pagers()[0]
        volume, page, _issue_page = ONE_PAGER_LOCATIONS[title]
        src = f"{page:03d}"
        dst = f"{ONE_PAGER_COLLECTION_PAGE_BASE:03d}"
        collection = stage_one_pagers.COLLECTION_VOLUME

        links = stage_one_pagers.get_staged_links_by_title(as_database(database))[title]

        assert links == [
            (
                database.get_fantagraphics_fixes_volume_image_dir(collection) / f"{dst}{JPG}",
                database.get_fantagraphics_volume_image_dir(volume) / f"{src}{JPG}",
            ),
            (
                database.get_fantagraphics_upscayled_volume_image_dir(collection) / f"{dst}{PNG}",
                database.get_fantagraphics_upscayled_volume_image_dir(volume) / f"{src}{PNG}",
            ),
            (
                database.get_fantagraphics_restored_volume_image_dir(collection) / f"{dst}{PNG}",
                database.get_fantagraphics_restored_volume_image_dir(volume) / f"{src}{PNG}",
            ),
            (
                database.get_fantagraphics_restored_svg_volume_image_dir(collection)
                / f"{dst}{SVG}",
                database.get_fantagraphics_restored_svg_volume_image_dir(volume) / f"{src}{SVG}",
            ),
            (
                database.get_fantagraphics_restored_svg_volume_image_dir(collection)
                / f"{dst}{SVG}{PNG}",
                database.get_fantagraphics_restored_svg_volume_image_dir(volume)
                / f"{src}{SVG}{PNG}",
            ),
            (
                database.get_fantagraphics_panel_segments_volume_dir(collection) / f"{dst}{JSON}",
                database.get_fantagraphics_panel_segments_volume_dir(volume) / f"{src}{JSON}",
            ),
        ]


class TestWhichSourceScanIsUsed:
    """A volume's original scan may have been superseded by a fixed one.

    Precedence is the build's, not staging's: `ComicBook._get_final_story_file` treats a
    fixes file as the edited version of that page, so staging must too. It did not, and
    the covers collection shipped nine pages built from originals whose fixes had been
    made weeks before - every image valid, every timestamp consistent, nothing to see.
    Each way that can go wrong is constructed here, since the failure has no symptom of
    its own to test for.
    """

    @staticmethod
    def _original_scan_link(database: FakeComicsDatabase) -> tuple[Path, Path]:
        """Return the first located one-pager's original-scan `(link, source)` pair."""
        links_by_title = stage_one_pagers.get_staged_links_by_title(as_database(database))
        title = get_located_one_pagers()[0]

        return next(
            (link, source)
            for link, source in links_by_title[title]
            if source.suffix in (JPG, PNG) and "upscayled" not in source.parts
        )

    @staticmethod
    def _first_one_pager_location() -> tuple[int, int]:
        title = get_located_one_pagers()[0]
        volume, page, _issue_page = ONE_PAGER_LOCATIONS[title]

        return volume, page

    def test_the_fixed_scan_supersedes_the_volumes_own_original(
        self, database: FakeComicsDatabase
    ) -> None:
        # The live bug: both exist, and the fix is the whole reason the page is in the
        # fixes tree, so staging the original silently drops the edit.
        volume, page = self._first_one_pager_location()
        touch(database.get_fantagraphics_volume_image_dir(volume) / f"{page:03d}{JPG}")
        fixed = touch(
            database.get_fantagraphics_fixes_volume_image_dir(volume) / f"{page:03d}{JPG}"
        )

        _link, source = self._original_scan_link(database)

        assert source == fixed

    def test_the_volumes_own_original_is_used_when_it_has_no_fix(
        self, database: FakeComicsDatabase
    ) -> None:
        volume, page = self._first_one_pager_location()
        original = touch(database.get_fantagraphics_volume_image_dir(volume) / f"{page:03d}{JPG}")

        _link, source = self._original_scan_link(database)

        assert source == original

    def test_the_fixes_scan_is_used_when_there_is_no_original(
        self, database: FakeComicsDatabase
    ) -> None:
        # A censorship fix or a fresh scan: the volume's read-only original never existed.
        volume, page = self._first_one_pager_location()
        fixed = touch(
            database.get_fantagraphics_fixes_volume_image_dir(volume) / f"{page:03d}{JPG}"
        )

        _link, source = self._original_scan_link(database)

        assert source == fixed

    def test_a_png_fix_is_seen(self, database: FakeComicsDatabase) -> None:
        # A fixes scan is saved in either extension, but staging only ever probed .jpg,
        # so a .png fix was not lost so much as invisible - the original went in its
        # place with nothing reporting a skip.
        volume, page = self._first_one_pager_location()
        touch(database.get_fantagraphics_volume_image_dir(volume) / f"{page:03d}{JPG}")
        fixed = touch(
            database.get_fantagraphics_fixes_volume_image_dir(volume) / f"{page:03d}{PNG}"
        )

        _link, source = self._original_scan_link(database)

        assert source == fixed

    def test_a_png_fix_keeps_its_extension_in_the_collection(
        self, database: FakeComicsDatabase
    ) -> None:
        # Staged under a fixed .jpg name it would be a png file that every later stage
        # reads as a jpg. The collection's fixes dir is looked up by both extensions.
        volume, page = self._first_one_pager_location()
        touch(database.get_fantagraphics_fixes_volume_image_dir(volume) / f"{page:03d}{PNG}")

        link, _source = self._original_scan_link(database)

        assert link.suffix == PNG

    def test_both_fix_extensions_at_once_is_refused(self, database: FakeComicsDatabase) -> None:
        # Which one supersedes the original is unanswerable, and either choice stages an
        # image nobody picked. The build refuses the same pair.
        volume, page = self._first_one_pager_location()
        touch(database.get_fantagraphics_fixes_volume_image_dir(volume) / f"{page:03d}{JPG}")
        touch(database.get_fantagraphics_fixes_volume_image_dir(volume) / f"{page:03d}{PNG}")

        with pytest.raises(RuntimeError, match=r"both \.jpg and \.png fixes file"):
            self._original_scan_link(database)

    def test_the_link_lands_in_the_collections_read_write_fixes_tree(
        self, database: FakeComicsDatabase
    ) -> None:
        # Not the collection's read-only original tree, so no permission changes are
        # needed to stage.
        link, _source = self._original_scan_link(database)

        assert "fixes" in link.parts


class TestWhichUpscayledScanIsUsed:
    """The upscayl has a fixes tree of its own, and so the same precedence again."""

    @staticmethod
    def _upscayled_source(database: FakeComicsDatabase) -> Path:
        links_by_title = stage_covers.get_staged_links_by_title(as_database(database))
        title = get_cover_title(get_located_covers()[0])

        return next(
            source
            for _link, source in links_by_title[title]
            if source.suffix == PNG and "upscayled" in "/".join(source.parts)
        )

    @staticmethod
    def _first_cover_location() -> tuple[int, int]:
        location = get_cover_location(get_located_covers()[0])
        assert location is not None

        return location

    def test_a_fixed_upscayl_supersedes_the_plain_one(self, database: FakeComicsDatabase) -> None:
        volume, page = self._first_cover_location()
        touch(database.get_fantagraphics_upscayled_volume_image_dir(volume) / f"{page:03d}{PNG}")
        fixed = touch(
            database.get_fantagraphics_upscayled_fixes_volume_image_dir(volume) / f"{page:03d}{PNG}"
        )

        assert self._upscayled_source(database) == fixed

    def test_the_plain_upscayl_is_used_when_it_has_no_fix(
        self, database: FakeComicsDatabase
    ) -> None:
        volume, page = self._first_cover_location()
        plain = database.get_fantagraphics_upscayled_volume_image_dir(volume) / f"{page:03d}{PNG}"
        touch(plain)

        assert self._upscayled_source(database) == plain


class TestStagingLinks:
    """What `stage` does on disk, for a member whose source files exist."""

    @staticmethod
    def _first_member_source(database: FakeComicsDatabase) -> Path:
        """Create and return the first located one-pager's original scan."""
        title = get_located_one_pagers()[0]
        volume, page, _issue_page = ONE_PAGER_LOCATIONS[title]

        return touch(database.get_fantagraphics_volume_image_dir(volume) / f"{page:03d}{JPG}")

    @staticmethod
    def _first_member_link(database: FakeComicsDatabase) -> Path:
        """Return where the first located one-pager's scan should be staged to."""
        links_by_title = stage_one_pagers.get_staged_links_by_title(as_database(database))
        title = get_located_one_pagers()[0]

        return next(link for link, source in links_by_title[title] if source.suffix == JPG)

    def test_a_source_that_exists_is_linked(self, database: FakeComicsDatabase) -> None:
        source = self._first_member_source(database)

        stage_one_pagers.stage(as_database(database), remove=False)

        link = self._first_member_link(database)
        assert link.is_symlink()
        assert link.resolve() == source.resolve()

    def test_a_stage_that_has_not_run_yet_is_left_alone(self, database: FakeComicsDatabase) -> None:
        # Outstanding work rather than a fault: the restore has simply not happened, and
        # linking a source that is not there would only make a dangling link.
        self._first_member_source(database)

        stage_one_pagers.stage(as_database(database), remove=False)

        links_by_title = stage_one_pagers.get_staged_links_by_title(as_database(database))
        title = get_located_one_pagers()[0]
        restored_link = next(
            link
            for link, source in links_by_title[title]
            if "restored" in source.parts and source.suffix == PNG
        )

        assert not restored_link.exists()

    def test_restaging_points_an_existing_link_at_the_new_source(
        self, database: FakeComicsDatabase, tmp_path: Path
    ) -> None:
        # The whole point of a restage after a location table change. Doing this by
        # replacing rather than creating is what stops it raising FileExistsError.
        self._first_member_source(database)
        stage_one_pagers.stage(as_database(database), remove=False)

        link = self._first_member_link(database)
        link.unlink()
        link.symlink_to(touch(tmp_path / "elsewhere" / "999.jpg"))

        stage_one_pagers.stage(as_database(database), remove=False)

        assert link.resolve() == self._first_member_source(database).resolve()

    def test_restaging_leaves_an_already_correct_link_untouched(
        self, database: FakeComicsDatabase
    ) -> None:
        # A restage must be safe to run at any time, which means a link that is already
        # right has to be left completely alone - including its mtime. `get_timestamp`
        # reads a symlink's own mtime, not its target's, so re-creating an unchanged link
        # moves that clock forward and the build then rejects a page whose panel-segments
        # file is still perfectly current. That is exactly what happened to the one-pager
        # at collection page 595: staged image, real segments file, and a restage that
        # changed nothing made the segments look stale.
        self._first_member_source(database)
        stage_one_pagers.stage(as_database(database), remove=False)
        link = self._first_member_link(database)
        before = link.lstat().st_mtime_ns

        stage_one_pagers.stage(as_database(database), remove=False)

        assert link.lstat().st_mtime_ns == before

    def test_restaging_a_link_whose_source_changed_moves_its_mtime(
        self, database: FakeComicsDatabase, tmp_path: Path
    ) -> None:
        # The other half of the same rule: leaving correct links alone must not blunt the
        # signal. A link that really did change source is rebuilt, so its mtime advances
        # and everything built from it is correctly seen as stale.
        self._first_member_source(database)
        stage_one_pagers.stage(as_database(database), remove=False)
        link = self._first_member_link(database)
        before = link.lstat().st_mtime_ns
        link.unlink()
        link.symlink_to(touch(tmp_path / "elsewhere" / "999.jpg"))

        stage_one_pagers.stage(as_database(database), remove=False)

        assert link.lstat().st_mtime_ns != before
        assert link.resolve() == self._first_member_source(database).resolve()

    def test_remove_deletes_the_link(self, database: FakeComicsDatabase) -> None:
        self._first_member_source(database)
        stage_one_pagers.stage(as_database(database), remove=False)
        link = self._first_member_link(database)
        assert link.is_symlink()

        stage_one_pagers.stage(as_database(database), remove=True)

        assert not link.is_symlink()

    def test_remove_deletes_a_dangling_link(self, database: FakeComicsDatabase) -> None:
        # `is_symlink()` is checked before `exists()`, so a link whose source has gone is
        # still cleaned up rather than being left behind forever.
        source = self._first_member_source(database)
        stage_one_pagers.stage(as_database(database), remove=False)
        link = self._first_member_link(database)
        source.unlink()
        assert link.is_symlink()
        assert not link.exists()

        stage_one_pagers.stage(as_database(database), remove=True)

        assert not link.is_symlink()


class TestSupersededSlots:
    """A page's staged slot is named after its source, so that name can change.

    `staged_link_for` gives the slot the source's own extension, so a page staged while
    its fix was a `.png` occupies `NNN.png`. Once that fix changes extension or is
    reverted, the slot that has to go is the *old* one, which neither staging nor
    removal can find by recomputing the source. Leaving it is not untidy but wrong: two
    fixes files for one page is the pair `_sole_fixes_file` and the build both refuse,
    and a leftover from a reverted fix is a dangling symlink the build still looks for.

    None of this was covered - deleting the whole superseded-slot cleanup from both
    stagers left every other test in the suite passing.
    """

    @staticmethod
    def _first_one_pager_location() -> tuple[int, int]:
        title = get_located_one_pagers()[0]
        volume, page, _issue_page = ONE_PAGER_LOCATIONS[title]

        return volume, page

    @staticmethod
    def _first_cover_location() -> tuple[int, int]:
        location = get_cover_location(get_located_covers()[0])
        assert location is not None

        return location

    @staticmethod
    def _staged_names(fixes_dir: Path, stem: str) -> list[str]:
        """Return what is staged in `fixes_dir` for collection page `stem`.

        Filtered by stem rather than listing the dir, so the assertions stay about this
        one page even if a member's own volume is also the collection volume.
        """
        if not fixes_dir.is_dir():
            return []

        return sorted(path.name for path in fixes_dir.iterdir() if path.name.startswith(stem))

    def test_restaging_a_fix_that_changed_extension_removes_the_old_slot(
        self, database: FakeComicsDatabase
    ) -> None:
        # The reason `superseded_links` exists. Restaging writes the new NNN.png; without
        # the cleanup the NNN.jpg from the previous staging stays beside it.
        volume, page = self._first_one_pager_location()
        volume_fixes = database.get_fantagraphics_fixes_volume_image_dir(volume)
        jpg_fix = touch(volume_fixes / f"{page:03d}{JPG}")
        stage_one_pagers.stage(as_database(database), remove=False)

        collection_fixes = database.get_fantagraphics_fixes_volume_image_dir(
            stage_one_pagers.COLLECTION_VOLUME
        )
        stem = f"{ONE_PAGER_COLLECTION_PAGE_BASE:03d}"
        assert self._staged_names(collection_fixes, stem) == [f"{stem}{JPG}"]

        # The editor re-saved the fix as a png, so the jpg it replaces is gone.
        jpg_fix.unlink()
        touch(volume_fixes / f"{page:03d}{PNG}")

        stage_one_pagers.stage(as_database(database), remove=False)

        assert self._staged_names(collection_fixes, stem) == [f"{stem}{PNG}"]

    def test_the_build_reads_the_new_extension_after_a_restage(
        self, database: FakeComicsDatabase
    ) -> None:
        # The consequence the cleanup buys, from the build's side rather than the
        # directory's: `original_scan_source` is how the collection's own fixes dir gets
        # read, and it refuses a page holding both extensions. Here the leftover would be
        # a dangling .jpg, which it skips - but once the collection page changes hands
        # (the table gained an entry, so this page now belongs to a different member) the
        # leftover still resolves, and this same call raises on a pair nobody authored.
        volume, page = self._first_one_pager_location()
        volume_fixes = database.get_fantagraphics_fixes_volume_image_dir(volume)
        jpg_fix = touch(volume_fixes / f"{page:03d}{JPG}")
        stage_one_pagers.stage(as_database(database), remove=False)
        jpg_fix.unlink()
        touch(volume_fixes / f"{page:03d}{PNG}")
        stage_one_pagers.stage(as_database(database), remove=False)

        staged = original_scan_source(
            as_database(database),
            stage_one_pagers.COLLECTION_VOLUME,
            f"{ONE_PAGER_COLLECTION_PAGE_BASE:03d}",
        )

        assert staged.suffix == PNG

    def test_remove_deletes_a_slot_staged_under_the_other_extension(
        self, database: FakeComicsDatabase
    ) -> None:
        # Staged from a .png fix, so the slot is NNN.png. Reverting the fix leaves the
        # volume's plain .jpg original, so a remove that recomputes the source looks for
        # NNN.jpg, deletes nothing, and reports success - and the collection's fixes dir
        # keeps a dangling NNN.png that `get_srce_original_fixes_story_file` still finds.
        volume, page = self._first_one_pager_location()
        png_fix = touch(
            database.get_fantagraphics_fixes_volume_image_dir(volume) / f"{page:03d}{PNG}"
        )
        stage_one_pagers.stage(as_database(database), remove=False)

        collection_fixes = database.get_fantagraphics_fixes_volume_image_dir(
            stage_one_pagers.COLLECTION_VOLUME
        )
        stem = f"{ONE_PAGER_COLLECTION_PAGE_BASE:03d}"
        assert self._staged_names(collection_fixes, stem) == [f"{stem}{PNG}"]

        png_fix.unlink()
        touch(database.get_fantagraphics_volume_image_dir(volume) / f"{page:03d}{JPG}")

        stage_one_pagers.stage(as_database(database), remove=True)

        assert self._staged_names(collection_fixes, stem) == []

    def test_remove_deletes_a_cover_slot_staged_under_the_other_extension(
        self, database: FakeComicsDatabase
    ) -> None:
        # The same through the covers wiring, since the bug was in both stagers.
        volume, page = self._first_cover_location()
        png_fix = touch(
            database.get_fantagraphics_fixes_volume_image_dir(volume) / f"{page:03d}{PNG}"
        )
        stage_covers.stage(as_database(database), remove=False, copy=False)

        collection_fixes = database.get_fantagraphics_fixes_volume_image_dir(
            stage_covers.COLLECTION_VOLUME
        )
        stem = f"{COVER_COLLECTION_PAGE_BASE:03d}"
        assert self._staged_names(collection_fixes, stem) == [f"{stem}{PNG}"]

        png_fix.unlink()
        touch(database.get_fantagraphics_volume_image_dir(volume) / f"{page:03d}{JPG}")

        stage_covers.stage(as_database(database), remove=True, copy=False)

        assert self._staged_names(collection_fixes, stem) == []

    def test_a_slot_supersedes_the_same_page_in_the_other_fix_extension(
        self, tmp_path: Path
    ) -> None:
        # The fixes pair, which is the whole point: either extension supersedes the
        # other, and neither supersedes itself.
        touch(tmp_path / f"519{JPG}")
        touch(tmp_path / f"519{PNG}")

        assert superseded_links(tmp_path / f"519{JPG}") == [tmp_path / f"519{PNG}"]
        assert superseded_links(tmp_path / f"519{PNG}") == [tmp_path / f"519{JPG}"]

    def test_the_restored_svg_pair_supersedes_only_its_own_double_suffix(
        self, tmp_path: Path
    ) -> None:
        # Only the last suffix is replaced, so "NNN.svg.png" yields "NNN.svg.jpg" and not
        # "NNN.jpg". Nothing writes a .svg.jpg, which is why staging the svg pair never
        # disturbs anything - the cleanup is only ever live in the fixes tree.
        for name in (f"519{JPG}", f"519{PNG}", f"519{SVG}", f"519{SVG}{PNG}"):
            touch(tmp_path / name)

        assert superseded_links(tmp_path / f"519{SVG}{PNG}") == []

        touch(tmp_path / f"519{SVG}{JPG}")

        assert superseded_links(tmp_path / f"519{SVG}{PNG}") == [tmp_path / f"519{SVG}{JPG}"]

    def test_a_slot_with_a_non_image_suffix_supersedes_both_image_names(
        self, tmp_path: Path
    ) -> None:
        # The panel-segments slot. Both image names are named, and neither is ever there
        # - that tree holds only .json, which is what keeps the cleanup safe to run over
        # every artifact rather than just the fixes one.
        touch(tmp_path / f"519{JSON}")

        assert superseded_links(tmp_path / f"519{JSON}") == []

        touch(tmp_path / f"519{JPG}")
        touch(tmp_path / f"519{PNG}")

        assert superseded_links(tmp_path / f"519{JSON}") == [
            tmp_path / f"519{JPG}",
            tmp_path / f"519{PNG}",
        ]

    def test_superseded_links_ignores_absent_siblings(self, tmp_path: Path) -> None:
        touch(tmp_path / f"519{JPG}")

        assert superseded_links(tmp_path / f"519{JPG}") == []

    def test_superseded_links_names_a_dangling_sibling(self, tmp_path: Path) -> None:
        # The leftover a reverted fix produces is a dangling symlink, and `exists()`
        # alone would not see it - which is the state `--remove` has to clean up.
        dangling = tmp_path / f"519{PNG}"
        dangling.symlink_to(tmp_path / "gone.png")

        assert superseded_links(tmp_path / f"519{JPG}") == [dangling]


class TestStagingCoversByCopy:
    """`barks-stage-covers --copy` exists for filesystems that cannot hold the links."""

    @staticmethod
    def _first_cover_link_and_source(database: FakeComicsDatabase) -> tuple[Path, Path]:
        """Create the first located cover's original scan and return its link pair."""
        links_by_title = stage_covers.get_staged_links_by_title(as_database(database))
        title = get_cover_title(get_located_covers()[0])
        link, source = next(
            (link, source) for link, source in links_by_title[title] if source.suffix == JPG
        )
        touch(source)

        return link, source

    def test_copy_produces_a_real_file_not_a_link(self, database: FakeComicsDatabase) -> None:
        link, _source = self._first_cover_link_and_source(database)

        stage_covers.stage(as_database(database), remove=False, copy=True)

        assert link.is_file()
        assert not link.is_symlink()

    def test_the_default_produces_a_link(self, database: FakeComicsDatabase) -> None:
        link, _source = self._first_cover_link_and_source(database)

        stage_covers.stage(as_database(database), remove=False, copy=False)

        assert link.is_symlink()

    def test_remove_deletes_a_copied_file_too(self, database: FakeComicsDatabase) -> None:
        link, _source = self._first_cover_link_and_source(database)
        stage_covers.stage(as_database(database), remove=False, copy=True)
        assert link.is_file()

        stage_covers.stage(as_database(database), remove=True, copy=False)

        assert not link.exists()


class TestTheTwoCollectionsAgree:
    def test_both_number_from_the_same_base(self) -> None:
        # They are different volumes, so the bases need not match - but they do, and a
        # reader of either module would assume it.
        assert COVER_COLLECTION_PAGE_BASE == ONE_PAGER_COLLECTION_PAGE_BASE

    def test_the_collections_are_staged_into_different_volumes(self) -> None:
        # Sharing a volume would make the two collections' page numbers collide, since
        # they number from the same base.
        assert stage_covers.COLLECTION_VOLUME != stage_one_pagers.COLLECTION_VOLUME
