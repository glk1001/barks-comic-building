"""Tests that every declared Fantagraphics volume names a directory that is really there.

A volume's `VOLUME_nn` constant is not a label - it *is* the directory name every source
path for that volume is built from, across all eleven Fantagraphics-* trees. So one wrong
word in it makes every lookup for that volume miss, and nothing downstream says so: the
stagers skip sources that are not files, and the integrity gate's directory-structure
check is satisfied by the derived dirs, which `make_all_fantagraphics_directories`
happily creates under whatever name it is given. The volume ends up looking present and
building nothing.

The original tree is the one place the name cannot be faked, because nothing creates it -
the scans are put there by hand. That makes "does the declared name exist under
Fantagraphics-original" the single check that pins the constants to reality, which is
what the first test below does for all of them at once.

Unlike this repo's other tests, those read the real comics library rather than a
`tmp_path` fake - there is no way to check the constants against reality without it. They
skip when the library is not mounted at all, since that is a machine that cannot answer
the question rather than a wrong constant. The two classes below cover the stagers' own
guards, and use a fake as usual.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from barks_fantagraphics.barks_covers import get_cover_location, get_located_covers
from barks_fantagraphics.comic_book_info import ONE_PAGER_LOCATIONS, get_located_one_pagers
from barks_fantagraphics.comics_consts import IMAGES_SUBDIR
from barks_fantagraphics.comics_database import ComicsDatabase
from barks_fantagraphics.fanta_comics_info import FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER

from barks_comic_building.build.stage_covers import missing_volume_dirs as missing_cover_volumes
from barks_comic_building.build.stage_one_pagers import missing_volume_dirs

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.barks_covers import BarksCover


def _cover_volume(cover: BarksCover) -> int:
    """Return a located cover's volume, narrowing away the None the table allows."""
    location = get_cover_location(cover)
    assert location is not None  # located by construction

    return location[0]


@pytest.fixture(scope="module")
def comics_database() -> ComicsDatabase:
    """Return the real database, skipping the tests when the comics library is absent."""
    database = ComicsDatabase(for_building_comics=True)

    original_root = database.get_fantagraphics_original_root_dir()
    if not original_root.is_dir():
        pytest.skip(f'No comics library mounted at "{original_root}".')

    return database


class TestEveryDeclaredVolumeIsOnDisk:
    """The `VOLUME_nn` constants agree with the directories in the original tree."""

    def test_every_declared_volume_has_an_original_dir(
        self, comics_database: ComicsDatabase
    ) -> None:
        missing = [
            (volume, comics_database.get_fantagraphics_volume_dir(volume))
            for volume in range(FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER + 1)
            if not comics_database.get_fantagraphics_volume_dir(volume).is_dir()
        ]

        assert not missing, (
            "Declared volume(s) missing from the Fantagraphics-original tree - the"
            " VOLUME_nn constant most likely disagrees with the directory on disk: "
            + ", ".join(f'volume {volume}: "{path.name}"' for volume, path in missing)
        )

    def test_every_declared_volume_has_an_original_images_dir(
        self, comics_database: ComicsDatabase
    ) -> None:
        # The volume dir existing is not enough: the scans live one level down, and that
        # is the directory the stagers and the build actually read from.
        missing = [
            (volume, comics_database.get_fantagraphics_volume_image_dir(volume))
            for volume in range(FIRST_VOLUME_NUMBER, LAST_VOLUME_NUMBER + 1)
            if not comics_database.get_fantagraphics_volume_image_dir(volume).is_dir()
        ]

        assert not missing, (
            "Declared volume(s) with no images dir in the Fantagraphics-original tree: "
            + ", ".join(f'volume {volume}: "{path}"' for volume, path in missing)
        )

    def test_every_located_one_pager_volume_is_on_disk(
        self, comics_database: ComicsDatabase
    ) -> None:
        # The same question the stager asks itself before it will run, asked against the
        # real library: this is the assertion that would have failed on the volume 30
        # one-pagers instead of them silently staging nothing.
        assert missing_volume_dirs(comics_database) == []

    def test_every_located_cover_volume_is_on_disk(self, comics_database: ComicsDatabase) -> None:
        # Covers draw on a different table and a wider spread of volumes than one-pagers
        # do, so their reachability is a separate question with the same answer shape.
        assert missing_cover_volumes(comics_database) == []


class _FakeComicsDatabase:
    """Just the original-tree accessor the guard uses, rooted under `tmp_path`."""

    def __init__(self, tmp_path: Path) -> None:
        self._root = tmp_path

    def get_fantagraphics_volume_image_dir(self, volume_num: int) -> Path:
        return self._root / "original" / f"volume-{volume_num:02d}" / IMAGES_SUBDIR


def _as_database(fake: _FakeComicsDatabase) -> ComicsDatabase:
    return cast("ComicsDatabase", fake)


class TestTheStagerGuardNamesTheOffendingVolumes:
    """`missing_volume_dirs` reports every volume a located one-pager cannot reach."""

    def test_all_volumes_missing_reports_each_one_once(self, tmp_path: Path) -> None:
        database = _as_database(_FakeComicsDatabase(tmp_path))

        missing = missing_volume_dirs(database)

        # Nothing was created under tmp_path, so every located one-pager's volume is
        # missing - but each volume is named once, however many one-pagers it holds.
        wanted = {ONE_PAGER_LOCATIONS[title][0] for title in get_located_one_pagers()}
        assert [volume for volume, _dir in missing] == sorted(wanted)

    def test_a_volume_that_exists_is_not_reported(self, tmp_path: Path) -> None:
        fake = _FakeComicsDatabase(tmp_path)
        wanted = sorted({ONE_PAGER_LOCATIONS[title][0] for title in get_located_one_pagers()})
        present = wanted[0]
        fake.get_fantagraphics_volume_image_dir(present).mkdir(parents=True)

        missing = missing_volume_dirs(_as_database(fake))

        assert [volume for volume, _dir in missing] == wanted[1:]

    def test_nothing_is_reported_when_every_volume_exists(self, tmp_path: Path) -> None:
        fake = _FakeComicsDatabase(tmp_path)
        for title in get_located_one_pagers():
            volume = ONE_PAGER_LOCATIONS[title][0]
            fake.get_fantagraphics_volume_image_dir(volume).mkdir(parents=True, exist_ok=True)

        assert missing_volume_dirs(_as_database(fake)) == []

    def test_the_reported_dir_is_the_one_that_was_looked_for(self, tmp_path: Path) -> None:
        fake = _FakeComicsDatabase(tmp_path)

        missing = dict(missing_volume_dirs(_as_database(fake)))

        volume, image_dir = next(iter(missing.items()))
        assert image_dir == fake.get_fantagraphics_volume_image_dir(volume)


class TestTheCoverGuardNamesTheOffendingVolumes:
    """`stage_covers.missing_volume_dirs` does the same over the cover location table."""

    def test_all_volumes_missing_reports_each_one_once(self, tmp_path: Path) -> None:
        database = _as_database(_FakeComicsDatabase(tmp_path))

        missing = missing_cover_volumes(database)

        wanted = {_cover_volume(cover) for cover in get_located_covers()}
        assert [volume for volume, _dir in missing] == sorted(wanted)

    def test_nothing_is_reported_when_every_volume_exists(self, tmp_path: Path) -> None:
        fake = _FakeComicsDatabase(tmp_path)
        for cover in get_located_covers():
            volume = _cover_volume(cover)
            fake.get_fantagraphics_volume_image_dir(volume).mkdir(parents=True, exist_ok=True)

        assert missing_cover_volumes(_as_database(fake)) == []

    def test_a_volume_that_exists_is_not_reported(self, tmp_path: Path) -> None:
        fake = _FakeComicsDatabase(tmp_path)
        wanted = sorted({_cover_volume(cover) for cover in get_located_covers()})
        present = wanted[0]
        fake.get_fantagraphics_volume_image_dir(present).mkdir(parents=True)

        missing = missing_cover_volumes(_as_database(fake))

        assert [volume for volume, _dir in missing] == wanted[1:]
