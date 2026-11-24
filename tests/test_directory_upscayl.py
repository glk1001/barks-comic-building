"""Tests for upscaling a directory of images that are not all pngs, or not all good."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from barks_comic_building.restore import directory_upscayl
from barks_comic_building.restore.directory_upscayl import upscale_directory
from barks_comic_building.restore.upscale_image import Upscaler

if TYPE_CHECKING:
    from pathlib import Path

SCALE = 4


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()

    return input_dir, output_dir


@pytest.fixture
def upscaled(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Stand a fake in for the upscale, recording the (input, output) names it was given.

    It keeps the one rule of the real thing that matters here - the output must be a
    png - and fails for any input whose name starts with "bad".
    """
    calls: list[tuple[str, str]] = []

    def upscale(in_file: Path, out_file: Path, _scale: int, _upscaler: Upscaler) -> None:
        assert out_file.suffix == ".png"
        if in_file.name.startswith("bad"):
            msg = "waifu2x exited cleanly but wrote no image."
            raise RuntimeError(msg)
        calls.append((in_file.name, out_file.name))
        out_file.write_bytes(b"upscaled")

    monkeypatch.setattr(directory_upscayl, "upscale_image_file", upscale)

    return calls


def run(dirs: tuple[Path, Path]) -> int:
    return upscale_directory(*dirs, SCALE, Upscaler.WAIFU2X)


def test_a_jpg_is_upscaled_to_a_png_of_the_same_stem(
    dirs: tuple[Path, Path], upscaled: list[tuple[str, str]]
) -> None:
    """The output kept the input's name, which the upscale refuses for a jpg."""
    (dirs[0] / "001.jpg").touch()
    (dirs[0] / "002.png").touch()

    assert run(dirs) == 0
    assert upscaled == [("001.jpg", "001.png"), ("002.png", "002.png")]


def test_one_bad_file_does_not_abandon_the_rest(
    dirs: tuple[Path, Path], upscaled: list[tuple[str, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("001.jpg", "bad-002.jpg", "003.jpg"):
        (dirs[0] / name).touch()

    assert run(dirs) == 1
    assert upscaled == [("001.jpg", "001.png"), ("003.jpg", "003.png")]
    assert 'Could not upscale "' in capsys.readouterr().out


def test_an_existing_output_is_left_alone(
    dirs: tuple[Path, Path], upscaled: list[tuple[str, str]]
) -> None:
    (dirs[0] / "001.jpg").touch()
    (dirs[1] / "001.png").write_bytes(b"already here")

    assert run(dirs) == 0
    assert upscaled == []
    assert (dirs[1] / "001.png").read_bytes() == b"already here"


def test_two_inputs_sharing_a_stem_do_not_overwrite_each_other(
    dirs: tuple[Path, Path], upscaled: list[tuple[str, str]]
) -> None:
    """Both would land on the same png; the first by name is made and the second skipped."""
    (dirs[0] / "001.png").touch()
    (dirs[0] / "001.jpg").touch()

    assert run(dirs) == 0
    assert upscaled == [("001.jpg", "001.png")]


def test_a_subdirectory_is_passed_over(
    dirs: tuple[Path, Path], upscaled: list[tuple[str, str]]
) -> None:
    (dirs[0] / "nested").mkdir()
    (dirs[0] / "001.jpg").touch()

    assert run(dirs) == 0
    assert upscaled == [("001.jpg", "001.png")]
