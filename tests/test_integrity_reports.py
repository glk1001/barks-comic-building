"""Tests that the integrity check says each thing once, and everything it knows.

Two ways a report misleads without being wrong about any one fact: saying the same
fault twice under two names, and stopping at the first fault so the second needs another
run to be seen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from barks_comic_building.build.comics_integrity import (
    ComicsIntegrityChecker,
    _stale_artifact_msg,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from barks_fantagraphics.comics_database import ComicsDatabase

READ_ONLY_DIR = 0o555
READ_ONLY_FILE = 0o444
WRITABLE_DIR = 0o755
WRITABLE_FILE = 0o644


def make_checker(database: object = None) -> ComicsIntegrityChecker:
    return ComicsIntegrityChecker(
        cast("ComicsDatabase", database or object()),
        no_check_for_unexpected_files=False,
        no_check_symlinks=False,
    )


class TestTheReadOnlySweep:
    @staticmethod
    def _tree(tmp_path: Path) -> tuple[Path, Path, Path]:
        """Make root/volume/page.jpg, all read-only; returns the three paths."""
        root = tmp_path / "original"
        volume = root / "volume"
        volume.mkdir(parents=True)
        page = volume / "001.jpg"
        page.touch()
        page.chmod(READ_ONLY_FILE)
        volume.chmod(READ_ONLY_DIR)
        root.chmod(READ_ONLY_DIR)

        return root, volume, page

    @staticmethod
    def _restore(*paths: Path) -> None:
        """Make the tree writable again so pytest can remove it."""
        for path in paths:
            path.chmod(WRITABLE_DIR)

    def test_a_read_only_tree_passes(self, tmp_path: Path) -> None:
        root, volume, _page = self._tree(tmp_path)

        try:
            assert make_checker().check_folder_and_contents_are_readonly(root) == 0
        finally:
            self._restore(root, volume)

    def test_a_writable_directory_is_reported_once_and_as_a_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Its contents are fine, which is the case that fell through to the file check.
        root, volume, _page = self._tree(tmp_path)
        volume.chmod(WRITABLE_DIR)

        try:
            assert make_checker().check_folder_and_contents_are_readonly(root) == 1
        finally:
            self._restore(root, volume)

        out = capsys.readouterr().out
        assert out.count("is not readonly") == 1
        assert f'Directory "{volume}"' in out

    def test_the_directory_passed_in_is_checked_too(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, volume, _page = self._tree(tmp_path)
        root.chmod(WRITABLE_DIR)

        try:
            assert make_checker().check_folder_and_contents_are_readonly(root) == 1
        finally:
            self._restore(root, volume)

        assert f'Directory "{root}"' in capsys.readouterr().out

    def test_a_writable_file_is_reported_as_a_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, volume, page = self._tree(tmp_path)
        page.chmod(WRITABLE_FILE)

        try:
            assert make_checker().check_folder_and_contents_are_readonly(root) == 1
        finally:
            self._restore(root, volume)

        assert f'File "{page}"' in capsys.readouterr().out


class FakeComic:
    def get_comic_title(self) -> str:
        return "A Title"


class FakeDatabase:
    def get_comic_book(self, _title: str) -> FakeComic:
        return FakeComic()


def recording_checker(
    monkeypatch: pytest.MonkeyPatch, *, structure: int, attributes: int
) -> tuple[ComicsIntegrityChecker, list[str]]:
    """Return a checker whose three per-title checks only record that they ran."""
    checker = make_checker(FakeDatabase())
    ran: list[str] = []

    def stub(name: str, result: int) -> object:
        return lambda *_args: ran.append(name) or result

    monkeypatch.setattr(checker, "check_comic_structure", stub("structure", structure))
    monkeypatch.setattr(checker, "check_story_attributes", stub("attributes", attributes))
    monkeypatch.setattr(checker, "check_out_of_date_files", stub("out of date", 0))

    return checker, ran


class TestOneRunShowsEveryFaultOfATitle:
    def test_a_structure_fault_does_not_hide_the_attributes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checker, ran = recording_checker(monkeypatch, structure=1, attributes=1)

        assert checker.check_single_title("A Title") == 1
        assert ran == ["structure", "attributes"]

    def test_a_clean_title_runs_all_three(self, monkeypatch: pytest.MonkeyPatch) -> None:
        checker, ran = recording_checker(monkeypatch, structure=0, attributes=0)

        assert checker.check_single_title("A Title") == 0
        assert ran == ["structure", "attributes", "out of date"]

    def test_an_attribute_fault_alone_fails_the_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checker, _ran = recording_checker(monkeypatch, structure=0, attributes=1)

        assert checker.check_single_title("A Title") == 1


class TestTheStaleArtifactMessage:
    def test_it_names_the_title_the_artifact_and_what_it_is_older_than(
        self, tmp_path: Path
    ) -> None:
        msg = _stale_artifact_msg(
            "A Title", "zip file", tmp_path / "a.cbz", 'the srce file "b.png"', 100.0, 200.0
        )

        lines = msg.split("\n")
        assert lines[0] == 'ERROR: For "A Title", the zip file'
        assert lines[1].strip() == f'"{tmp_path / "a.cbz"}"'
        assert lines[2].strip() == 'is out of date with the srce file "b.png"'
        assert " < " in lines[3]

    def test_continuation_lines_are_indented_to_the_prefix(self, tmp_path: Path) -> None:
        msg = _stale_artifact_msg("A Title", "year symlink", tmp_path / "a", "x", 1.0, 2.0)

        assert all(line.startswith(" " * len("ERROR: ")) for line in msg.split("\n")[1:])
