from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from barks_fantagraphics.comics_utils import get_relpath
from loguru import logger

if TYPE_CHECKING:
    from barks_fantagraphics.comic_book import ComicBook


def zip_comic_book(comic: ComicBook) -> None:
    logger.info(
        f'Zipping directory "{get_relpath(comic.get_dest_dir())}" to'
        f' "{get_relpath(comic.get_dest_comic_zip())}".',
    )

    os.makedirs(comic.get_dest_zip_root_dir(), exist_ok=True)
    temp_zip_file = comic.get_dest_dir() + ".zip"

    shutil.make_archive(comic.get_dest_dir(), "zip", comic.get_dest_dir())
    if not os.path.isfile(temp_zip_file):
        msg = f'Could not create temporary zip file "{temp_zip_file}".'
        raise RuntimeError(msg)

    os.replace(temp_zip_file, comic.get_dest_comic_zip())
    if not os.path.isfile(comic.get_dest_comic_zip()):
        msg = f'Could not create final comic zip "{comic.get_dest_comic_zip()}".'
        raise RuntimeError(msg)


def create_symlinks_to_comic_zip(comic: ComicBook) -> None:
    if not os.path.exists(comic.get_dest_comic_zip()):
        msg = f'Could not find comic zip file "{comic.get_dest_comic_zip()}".'
        raise FileNotFoundError(msg)

    create_symlink_zip(
        comic.get_dest_comic_zip(),
        comic.get_dest_series_zip_symlink_dir(),
        comic.get_dest_series_comic_zip_symlink(),
    )

    create_symlink_zip(
        comic.get_dest_comic_zip(),
        comic.get_dest_year_zip_symlink_dir(),
        comic.get_dest_year_comic_zip_symlink(),
    )


def create_symlink_zip(zip_file: str, symlink_dir: str, symlink: str) -> None:
    logger.info(
        f'Symlinking (relative) the comic zip file "{get_relpath(zip_file)}" to'
        f' "{get_relpath(symlink)}".',
    )

    if not os.path.exists(symlink_dir):
        os.makedirs(symlink_dir)
    if os.path.islink(symlink):
        os.remove(symlink)

    relative_symlink(zip_file, symlink)
    if not os.path.islink(symlink):
        msg = f'Could not create symlink "{symlink}".'
        raise RuntimeError(msg)


def relative_symlink(target: Path | str, destination: Path | str) -> None:
    """Create a symlink pointing to ``target`` from ``location``.

    Args:
        target: The target of the symlink (the file/directory that is pointed to)
        destination: The location of the symlink itself.

    """
    target = Path(target)
    destination = Path(destination)

    target_dir = destination.parent
    target_dir.mkdir(exist_ok=True, parents=True)

    relative_source = os.path.relpath(target, target_dir)

    logger.debug(f'"{relative_source}" -> "{destination.name}" in "{get_relpath(target_dir)}"')
    target_dir_fd = os.open(str(target_dir.absolute()), os.O_RDONLY)
    try:
        os.symlink(relative_source, destination.name, dir_fd=target_dir_fd)
    finally:
        os.close(target_dir_fd)
