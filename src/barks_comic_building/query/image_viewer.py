"""Open the desktop's image viewer on a file, for the tools that show a page."""
# ruff: noqa: T201

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

VIEWER_EXE = ["/usr/bin/loupe"]


def open_viewer(image_file: Path) -> None:
    """Start the image viewer on an image, and leave it running.

    Args:
        image_file: The image to show.

    """
    command = [*VIEWER_EXE, str(image_file)]

    _proc = subprocess.Popen(command)  # noqa: S603

    print(f'Image Viewer should now be showing image "{image_file}".')
