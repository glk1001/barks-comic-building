"""Tests for archiving a built comic and linking it into the browse trees.

Two properties here are load-bearing and neither is obvious from the call site.

The zip's files sit at the archive *root*, not nested under a directory named after the
comic. A reader opening the cbz expects to find pages, not one folder containing pages,
so nesting them would break every built archive at once while leaving the build green.

The symlinks are *relative*. That is why `artifact_renaming` can rename a whole tree of
built comics and re-point the links afterwards: an absolute link would survive a rename
of the zip but not a rename of any directory above it. The test below renames the tree to
prove it.
"""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING, cast

import pytest

from barks_comic_building.build.zipping import (
    create_symlink_zip,
    create_symlinks_to_comic_zip,
    relative_symlink,
    zip_comic_book,
)

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comic_book import ComicBook

PAGES = ["001.jpg", "002.jpg", "003.jpg"]


def touch(path: Path) -> Path:
    """Create an empty file, making its parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()

    return path


class FakeComic:
    """The dest paths the zipping step reads, all under `tmp_path`.

    Stands in for a `ComicBook`: only the accessors `zip_comic_book` and
    `create_symlinks_to_comic_zip` call are implemented, so no comics database or ini
    file is needed. The directory layout mirrors the real one - the zip root is the dest
    directory's parent, and the two symlink trees are siblings of it.
    """

    def __init__(self, tmp_path: Path) -> None:
        # One level below `tmp_path`, so a test can rename the whole library without
        # touching the directory pytest is managing.
        self.library = tmp_path / "library"
        self.dest_dir = self.library / "Chronological" / "042 A Fake Title"
        self.zip_root = self.library / "Comics"
        self.zip_file = self.zip_root / "A Fake Title.cbz"
        self.series_dir = self.library / "Series" / "Donald Duck"
        self.year_dir = self.library / "Years" / "1949"

    def get_dest_dir(self) -> Path:
        return self.dest_dir

    def get_dest_zip_root_dir(self) -> Path:
        return self.zip_root

    def get_dest_comic_zip(self) -> Path:
        return self.zip_file

    def get_dest_series_zip_symlink_dir(self) -> Path:
        return self.series_dir

    def get_dest_series_comic_zip_symlink(self) -> Path:
        return self.series_dir / self.zip_file.name

    def get_dest_year_zip_symlink_dir(self) -> Path:
        return self.year_dir

    def get_dest_year_comic_zip_symlink(self) -> Path:
        return self.year_dir / self.zip_file.name

    def write_pages(self) -> None:
        """Fill the dest directory with pages, as a completed build would leave it."""
        for page in PAGES:
            touch(self.dest_dir / page)


def as_comic(fake: FakeComic) -> ComicBook:
    """Present a `FakeComic` as the `ComicBook` the zipping step is typed against."""
    return cast("ComicBook", fake)


@pytest.fixture
def comic(tmp_path: Path) -> FakeComic:
    fake = FakeComic(tmp_path)
    fake.write_pages()

    return fake


class TestZippingTheComic:
    def test_the_pages_land_at_the_archive_root(self, comic: FakeComic) -> None:
        # Not nested under a directory named after the comic, which is what a reader
        # opening the cbz depends on.
        zip_comic_book(as_comic(comic))

        with zipfile.ZipFile(comic.zip_file) as archive:
            assert sorted(archive.namelist()) == PAGES

    def test_the_zip_is_written_where_the_comic_says(self, comic: FakeComic) -> None:
        zip_comic_book(as_comic(comic))

        assert comic.zip_file.is_file()

    def test_the_zip_root_is_created_if_it_is_not_there(self, comic: FakeComic) -> None:
        assert not comic.zip_root.exists()

        zip_comic_book(as_comic(comic))

        assert comic.zip_root.is_dir()

    def test_no_temporary_archive_is_left_beside_the_dest_directory(self, comic: FakeComic) -> None:
        # `shutil.make_archive` writes next to the source, and the result is then moved
        # into place. A leftover would read as an unexpected file to the integrity check.
        zip_comic_book(as_comic(comic))

        leftover = comic.dest_dir.with_name(f"{comic.dest_dir.name}.zip")
        assert not leftover.exists()

    def test_rebuilding_replaces_the_previous_zip(self, comic: FakeComic) -> None:
        zip_comic_book(as_comic(comic))
        (comic.dest_dir / "004.jpg").touch()

        zip_comic_book(as_comic(comic))

        with zipfile.ZipFile(comic.zip_file) as archive:
            assert "004.jpg" in archive.namelist()


class TestTheSymlinksAreRelative:
    """The property that lets a built tree be renamed without re-linking every zip."""

    def test_the_link_target_is_not_absolute(self, comic: FakeComic) -> None:
        zip_comic_book(as_comic(comic))

        create_symlinks_to_comic_zip(as_comic(comic))

        target = comic.get_dest_series_comic_zip_symlink().readlink()
        assert not target.is_absolute()

    def test_the_link_walks_up_out_of_its_own_directory(self, comic: FakeComic) -> None:
        zip_comic_book(as_comic(comic))

        create_symlinks_to_comic_zip(as_comic(comic))

        target = comic.get_dest_series_comic_zip_symlink().readlink()
        assert ".." in target.parts

    def test_the_link_still_resolves_after_the_tree_above_is_renamed(
        self, comic: FakeComic
    ) -> None:
        # The whole point of a relative link. An absolute one would break here, and this
        # is what `artifact_renaming` relies on when it moves a built tree.
        zip_comic_book(as_comic(comic))
        create_symlinks_to_comic_zip(as_comic(comic))

        moved = comic.library.with_name("renamed-library")
        comic.library.rename(moved)

        symlink = moved / "Series" / "Donald Duck" / comic.zip_file.name
        assert symlink.is_symlink()
        assert symlink.resolve().is_file()


class TestCreatingTheSymlinks:
    def test_both_the_series_and_year_links_are_made(self, comic: FakeComic) -> None:
        zip_comic_book(as_comic(comic))

        create_symlinks_to_comic_zip(as_comic(comic))

        assert comic.get_dest_series_comic_zip_symlink().is_symlink()
        assert comic.get_dest_year_comic_zip_symlink().is_symlink()

    def test_both_links_point_at_the_zip(self, comic: FakeComic) -> None:
        zip_comic_book(as_comic(comic))

        create_symlinks_to_comic_zip(as_comic(comic))

        for symlink in (
            comic.get_dest_series_comic_zip_symlink(),
            comic.get_dest_year_comic_zip_symlink(),
        ):
            assert symlink.resolve() == comic.zip_file.resolve()

    def test_a_missing_zip_is_refused_rather_than_linked_to(self, comic: FakeComic) -> None:
        # A dangling link would look like a built comic to anything browsing the tree.
        with pytest.raises(FileNotFoundError, match="Could not find comic zip"):
            create_symlinks_to_comic_zip(as_comic(comic))

    def test_an_existing_link_is_replaced(self, comic: FakeComic) -> None:
        zip_comic_book(as_comic(comic))
        symlink = comic.get_dest_series_comic_zip_symlink()
        symlink.parent.mkdir(parents=True, exist_ok=True)
        symlink.symlink_to(touch(comic.dest_dir / "stale.cbz"))

        create_symlink_zip(comic.zip_file, comic.series_dir, symlink)

        assert symlink.resolve() == comic.zip_file.resolve()

    def test_the_symlink_directory_is_created_if_it_is_not_there(self, comic: FakeComic) -> None:
        zip_comic_book(as_comic(comic))
        assert not comic.series_dir.exists()

        create_symlink_zip(
            comic.zip_file, comic.series_dir, comic.get_dest_series_comic_zip_symlink()
        )

        assert comic.series_dir.is_dir()


class TestRelativeSymlink:
    def test_a_sibling_target_needs_no_walking_up(self, tmp_path: Path) -> None:
        target = touch(tmp_path / "dir" / "target.cbz")
        destination = tmp_path / "dir" / "link.cbz"

        relative_symlink(target, destination)

        assert destination.readlink().parts == ("target.cbz",)

    def test_the_destination_directory_is_created(self, tmp_path: Path) -> None:
        target = touch(tmp_path / "target.cbz")
        destination = tmp_path / "not" / "yet" / "link.cbz"

        relative_symlink(target, destination)

        assert destination.is_symlink()
        assert destination.resolve() == target.resolve()

    def test_a_target_that_does_not_exist_still_links(self, tmp_path: Path) -> None:
        # `relative_symlink` is the primitive; refusing a missing target is the caller's
        # job, and `create_symlinks_to_comic_zip` does exactly that.
        target = tmp_path / "dir" / "gone.cbz"
        destination = tmp_path / "other" / "link.cbz"

        relative_symlink(target, destination)

        assert destination.is_symlink()
        assert not destination.exists()
