"""Tests for the one place the page-showing tools start the image viewer from."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from barks_comic_building.query import image_viewer, show_title_page, show_volume_page

if TYPE_CHECKING:
    import pytest


def test_the_viewer_is_started_on_the_file_and_not_waited_for(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started = []
    monkeypatch.setattr(image_viewer.subprocess, "Popen", started.append)

    image_viewer.open_viewer(Path("/library/restored/227.png"))

    assert started == [[*image_viewer.VIEWER_EXE, "/library/restored/227.png"]]
    assert '"/library/restored/227.png"' in capsys.readouterr().out


def test_both_page_tools_use_the_one_viewer() -> None:
    # Each had its own copy of the helper and of the viewer's path.
    assert show_title_page.open_viewer is image_viewer.open_viewer
    assert show_volume_page.open_viewer is image_viewer.open_viewer
