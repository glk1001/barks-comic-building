"""Find a title's page in one of the per-volume trees, for the tools that open one."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from barks_fantagraphics.barks_titles import STR_TITLE_TO_ENUM
from barks_fantagraphics.comic_book_info import (
    ONE_PAGERS,
    get_located_one_pagers,
    get_one_pager_fanta_vol_and_page,
    get_one_pager_file,
    is_one_pager_located,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def get_title_page_file(
    title: str,
    volume: int,
    page: str,
    get_volume_dir: Callable[[int], Path],
    suffix: str,
) -> Path:
    """Return a title's page file in one of the per-volume trees, wherever it lives.

    For a story that is the volume's own file. A one-pager that belongs to no story is
    processed only as a page of "All One-Pagers", so its restored page and its panel
    segments are in the collection's volume under its collection page and its home
    volume never has them. Looking only in the home volume told the user a page that had
    been restored for months could not be found.

    Args:
        title: The title the page belongs to.
        volume: The title's Fantagraphics volume.
        page: The page, as it appears in a filename ("227").
        get_volume_dir: The tree's per-volume directory, e.g.
            `ComicsDatabase.get_fantagraphics_restored_volume_image_dir`.
        suffix: What follows the page number in the file name, e.g. ".png" or ".json".

    Returns:
        The file, whether or not it exists. For a one-pager in neither place it is the
        home volume's path, so a report of a missing file names the home volume.

    """
    title_enum = STR_TITLE_TO_ENUM.get(title)
    if title_enum in ONE_PAGERS and is_one_pager_located(title_enum):
        return get_one_pager_file(title_enum, get_volume_dir, suffix)

    return Path(get_volume_dir(volume)) / (page + suffix)


def get_volume_page_file(
    volume: int,
    page_num: int,
    get_volume_dir: Callable[[int], Path],
    suffix: str,
) -> Path:
    """Return a volume's page file in one of the per-volume trees, wherever it lives.

    The page is named by where it is in the Fantagraphics book, with no title to say
    what it is. When that place is a one-pager's, the file is looked for as
    `get_title_page_file` looks for the one-pager: in the volume, then in the
    collection's volume, where a one-pager that belongs to no story is processed.

    Args:
        volume: The Fantagraphics volume.
        page_num: The page's number in that volume.
        get_volume_dir: The tree's per-volume directory, e.g.
            `ComicsDatabase.get_fantagraphics_restored_volume_image_dir`.
        suffix: What follows the page number in the file name, e.g. ".png" or ".json".

    Returns:
        The file, whether or not it exists. In neither place, it is the volume's own
        path, so a report of a missing file names the volume that was asked for.

    """
    for one_pager in get_located_one_pagers():
        if get_one_pager_fanta_vol_and_page(one_pager) == (volume, page_num):
            return get_one_pager_file(one_pager, get_volume_dir, suffix)

    return Path(get_volume_dir(volume)) / f"{page_num:03d}{suffix}"
