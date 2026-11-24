"""Deciding whether a page still needs restoring.

The old test was whether the restored png existed. That misses two things. It cannot tell
a page made with the current tuning from one made under settings that have since changed,
so a re-run after a tuning change meant deleting outputs by hand. And it looks at only one
of the four files a restore produces, so a page whose 4x or svg output never got written
was skipped from then on - there are over a hundred such pages in the library today,
mostly in volumes 1 and 7.

Both are the same question asked properly: are all of this page's outputs present, and
were they made with the recipe in force now.

There is a third thing the recipe cannot answer, because it describes what the restore
does and says nothing of what it was handed: whether the page was made from the upscayled
input that is there now. So the restored page also records which upscale it was made from,
and a page made from an input that has since been redone is as stale as one made under old
settings.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, Protocol

from barks_fantagraphics.comics_consts import RESTORABLE_PAGE_TYPES

from barks_comic_building.restore.image_io import read_png_metadata
from barks_comic_building.restore.upscale_image import (
    UPSCALER_KEY,
    UPSCAYL_MODEL_KEY,
    WAIFU2X_MODEL_KEY,
    Upscaler,
)
from barks_comic_building.restore.upscale_state import RECIPE_ID_KEY as UPSCALE_RECIPE_ID_KEY
from barks_comic_building.restore.upscale_state import UPSCALE_DATE_KEY

if TYPE_CHECKING:
    from collections.abc import Iterator

    from barks_fantagraphics.comic_book import ModifiedType
    from barks_fantagraphics.comics_consts import PageType

__all__ = [
    "UPSCALER_KEY",
    "PageState",
    "PageStatus",
    "RestorePage",
    "get_ink_mask_file",
    "get_page_status",
    "get_upscaler_used",
    "get_upscayl_input_stamp",
    "walk_restore_pages",
]

# The png metadata keys the restore stamps its provenance into.
RECIPE_ID_KEY = "Restore recipe id"
RECIPE_KEY = "Restore recipe"
RESTORE_DATE_KEY = "Restore date"

# The keys the restore records its input under: the recipe and date the upscayled page it
# worked from was carrying. Together they name one particular upscale of the page, since
# the date moves every time the page is upscayled again, whatever it is upscayled with.
INPUT_RECIPE_ID_KEY = "Upscayl input recipe id"
INPUT_DATE_KEY = "Upscayl input date"
_INPUT_KEYS = (INPUT_RECIPE_ID_KEY, INPUT_DATE_KEY)


class PageState(StrEnum):
    """Where a page stands relative to the recipe in force now."""

    CURRENT = "current"
    """Every output is present and was made with the current recipe. Nothing to do."""

    STALE = "stale"
    """Every output is present, but made with different settings, or with none recorded,
    or from an upscayled input that has since been redone. Pages restored before
    provenance was kept land here, which is what makes the first run after this change
    redo the library without anything being deleted first."""

    INCOMPLETE = "incomplete"
    """Some outputs exist and some do not. Under the old existence check these were
    invisible whenever the restored png happened to be one of the ones present."""

    MISSING = "missing"
    """None of the outputs exist."""

    LINKED = "linked"
    """An output is a symlink to a page of another volume, which owns it.

    Collection titles borrow pages this way - volume 1 carries a hundred of them - and
    the page they point at is restored as part of its own volume. Writing here would
    follow the link and overwrite that volume's page, from a different source image, so
    a linked page is never this run's to make."""

    HAND_RESTORED = "hand-restored"
    """The restored page was made by hand, and is what a run would write over.

    Two kinds, both declared in `HAND_RESTORED_TITLES` / `HAND_RESTORED_PAGES` rather than
    detected. A page of a hand-restored title, whose restored output the build never even
    reads - `get_final_srce_story_file` goes to the fixes tree for those titles. And an
    individually declared page like volume 4's 227, whose restored png *is* the hand work.

    Neither carries a recipe of ours, so the recipe test calls both stale and a run would
    redo them: the first wasting hours on output nothing consumes, the second destroying a
    page that no re-run can make again. Declared rather than detected because the only
    trace on disk is a missing metadata key, which is also what an interrupted write
    leaves. Never this run's to make, not even under --force."""

    NO_SRCE = "no-srce"
    """The upscayled input is not there, so the page cannot be restored at all."""

    @property
    def needs_restoring(self) -> bool:
        """Whether a page in this state should be put through the pipeline."""
        return self in (PageState.STALE, PageState.INCOMPLETE, PageState.MISSING)


class PageStatus(NamedTuple):
    """A page's state, and the provenance behind it."""

    state: PageState
    recipe_id: str
    restore_date: str

    @property
    def needs_restoring(self) -> bool:
        """Whether this page should be put through the pipeline."""
        return self.state.needs_restoring


def get_ink_mask_file(dest_svg_restored_file: Path) -> Path:
    """Return the path of the ink mask that ships beside a page's traced line art.

    Args:
        dest_svg_restored_file: The traced line art.

    Returns:
        The same path with ``.png`` added, which is where the reader looks for it.

    """
    return dest_svg_restored_file.with_name(dest_svg_restored_file.name + ".png")


def get_upscayl_input_stamp(srce_upscayl_file: Path) -> dict[str, str]:
    """Return what a restore records about the upscayled page it was made from.

    Args:
        srce_upscayl_file: The upscayled page.

    Returns:
        The input's upscale recipe id and date, under the keys they are written to the
        restored page with. Empty if the input carries either one but not both, or
        neither - a hand-edited page in the upscayled fixes tree carries neither - since
        half a name identifies nothing.

    """
    metadata = read_png_metadata(srce_upscayl_file)

    recipe_id = metadata.get(UPSCALE_RECIPE_ID_KEY, "")
    upscale_date = metadata.get(UPSCALE_DATE_KEY, "")
    if not recipe_id or not upscale_date:
        return {}

    return {INPUT_RECIPE_ID_KEY: recipe_id, INPUT_DATE_KEY: upscale_date}


def _is_made_from_this_input(
    srce_upscayl_file: Path, dest_restored_file: Path, restored_metadata: dict[str, str]
) -> bool:
    """Return whether a restored page was made from the upscayled input that is there now.

    Answered from what the two files say about themselves when both say it: the restored
    page names the upscale it was made from, and the input says which upscale it is.

    When either is silent the file times are all there is to go on, and a restored page
    older than its input cannot have been made from it. The whole library was restored
    before this was recorded, and a hand-edited input carries no upscale of ours to name,
    so this is the answer for most pages until they are next restored. It is the weaker
    of the two - copying the upscayled tree makes every page look newer than its
    restoration - which is why it is only the fallback.
    """
    current = get_upscayl_input_stamp(srce_upscayl_file)
    recorded = {key: restored_metadata[key] for key in _INPUT_KEYS if key in restored_metadata}

    if current and len(recorded) == len(_INPUT_KEYS):
        return recorded == current

    try:
        return dest_restored_file.stat().st_mtime_ns >= srce_upscayl_file.stat().st_mtime_ns
    except OSError:
        return False


# One parameter per thing the answer depends on, and one return per state, because the
# body is a chain of guard clauses in the order the questions have to be asked. Collapsing
# either would hide the ordering, which is the part that matters here.
def get_page_status(  # noqa: PLR0911, PLR0913
    srce_upscayl_file: Path,
    dest_restored_file: Path,
    dest_upscayled_restored_file: Path,
    dest_svg_restored_file: Path,
    current_recipe_id: str,
    *,
    is_hand_restored: bool,
) -> PageStatus:
    """Work out whether a page still needs restoring.

    Args:
        srce_upscayl_file: The upscayled page the restore works from.
        dest_restored_file: The restored page at source size.
        dest_upscayled_restored_file: The restored page at full scale.
        dest_svg_restored_file: The traced line art. The ink mask beside it is the
            fourth output, and its path follows from this one.
        current_recipe_id: The id of the recipe the pipeline would use now.
        is_hand_restored: Whether this page's restored file was made by hand -
            `ComicBook.is_hand_restored`. Deliberately required rather than defaulted: a
            caller that forgets it queues the hand work for overwriting, which is exactly
            how volume 4's page 227 came to be one run away from being lost.

    Returns:
        The page's state, with the recipe id and date read off the restored png when it
        has them.

    """
    # The ink mask is the last file a restore writes and the only one of the four not
    # named by a caller. Left out of this list, a page whose mask never got written read
    # as CURRENT and was never looked at again.
    outputs = [
        dest_restored_file,
        dest_upscayled_restored_file,
        dest_svg_restored_file,
        get_ink_mask_file(dest_svg_restored_file),
    ]

    # These two come first, and neither looks at the recipe, because for both the question
    # "is this page up to date" is not this run's to answer - and answering it here is done
    # by destroying something.

    # A symlink among the outputs means this page is another volume's, and whether it is up
    # to date is that volume's question. Asked here it would be answered by writing through
    # the link. Tested before the hand-restored check because a page can be both, and the
    # volume that owns it is the more useful of the two things to be told.
    if any(file.is_symlink() for file in outputs):
        return PageStatus(PageState.LINKED, "", "")

    # Made by hand. This is deliberately answered before anything about the input or which
    # outputs exist: those describe the page's ancestry, while this describes whose work
    # the output is. Volume 4's 227 has no original scan and is spared NO_SRCE today only
    # because its upscayled-fixes png happens to exist; and if a hand page's outputs were
    # deleted, a run must still not put a machine restore in their place.
    if is_hand_restored:
        return PageStatus(PageState.HAND_RESTORED, "", "")

    if not srce_upscayl_file.is_file():
        return PageStatus(PageState.NO_SRCE, "", "")

    num_present = sum(1 for file in outputs if file.is_file())

    if num_present == 0:
        return PageStatus(PageState.MISSING, "", "")

    if num_present < len(outputs):
        return PageStatus(PageState.INCOMPLETE, "", "")

    metadata = read_png_metadata(dest_restored_file)
    recipe_id = metadata.get(RECIPE_ID_KEY, "")
    restore_date = metadata.get(RESTORE_DATE_KEY, "")

    # The recipe first, because it is read off a file already open; the input is only
    # worth reading for a page that would otherwise be called finished.
    if (
        recipe_id
        and recipe_id == current_recipe_id
        and _is_made_from_this_input(srce_upscayl_file, dest_restored_file, metadata)
    ):
        return PageStatus(PageState.CURRENT, recipe_id, restore_date)

    return PageStatus(PageState.STALE, recipe_id, restore_date)


class RestorePage(NamedTuple):
    """One restorable page of a title: its files, and where it stands."""

    page: str
    """The page's file stem, as it is named in the volume."""

    srce_file: Path
    """The original scan, which the palette snap reads. May not exist."""

    srce_upscayl_file: Path
    dest_restored_file: Path
    dest_upscayled_restored_file: Path
    dest_svg_restored_file: Path
    status: PageStatus


class _RestorableComic(Protocol):
    """What the walk asks of a comic. `ComicBook` is the one that answers."""

    def get_final_srce_original_story_files(
        self, page_types: list[PageType], /
    ) -> list[tuple[Path, ModifiedType]]: ...

    def get_final_srce_upscayled_story_files(
        self, page_types: list[PageType], /
    ) -> list[tuple[Path, ModifiedType]]: ...

    def get_srce_restored_story_files(self, page_types: list[PageType], /) -> list[Path]: ...

    def get_srce_restored_upscayled_story_files(
        self, page_types: list[PageType], /
    ) -> list[Path]: ...

    def get_srce_restored_svg_story_files(self, page_types: list[PageType], /) -> list[Path]: ...

    def is_hand_restored(self, page_num: str, /) -> bool: ...


def walk_restore_pages(comic: _RestorableComic, current_recipe_id: str) -> Iterator[RestorePage]:
    """Yield every restorable page of a title with its files and its state.

    The one place that lines a title's five file lists up against each other and asks
    where each page stands. The run that restores pages and the report that says what a
    run would do both read it from here, so the report cannot say a page is waiting that
    the run is going to pass over. They used to each have their own copy of this loop,
    and a change to how a page is judged had to be made in both to be true of both.

    Args:
        comic: The title to walk.
        current_recipe_id: The id of the recipe the pipeline would use now.

    Yields:
        Each restorable page, in page order.

    """
    for (srce_file, _), (srce_upscayl_file, _), restored, upscayled_restored, svg in zip(
        comic.get_final_srce_original_story_files(RESTORABLE_PAGE_TYPES),
        comic.get_final_srce_upscayled_story_files(RESTORABLE_PAGE_TYPES),
        comic.get_srce_restored_story_files(RESTORABLE_PAGE_TYPES),
        comic.get_srce_restored_upscayled_story_files(RESTORABLE_PAGE_TYPES),
        comic.get_srce_restored_svg_story_files(RESTORABLE_PAGE_TYPES),
        strict=True,
    ):
        dest_restored_file = Path(restored)
        page = dest_restored_file.stem

        yield RestorePage(
            page=page,
            srce_file=Path(srce_file),
            srce_upscayl_file=Path(srce_upscayl_file),
            dest_restored_file=dest_restored_file,
            dest_upscayled_restored_file=Path(upscayled_restored),
            dest_svg_restored_file=Path(svg),
            status=get_page_status(
                Path(srce_upscayl_file),
                dest_restored_file,
                Path(upscayled_restored),
                Path(svg),
                current_recipe_id,
                is_hand_restored=comic.is_hand_restored(page),
            ),
        )


def get_upscaler_used(srce_upscayl_file: Path) -> str:
    """Return which upscaler made a page's input, from that file's own metadata.

    Upstream provenance rather than part of the restore recipe: it describes the input
    the restore was handed, not what the restore did with it.

    Pages upscayled before the "Upscaler" key existed - which is the whole library as it
    stands - carry only their backend's model key. That names the backend just as
    definitely, so it is read as a fallback rather than leaving the field blank on every
    page until the library has been through the upscale again.

    Args:
        srce_upscayl_file: The upscayled page.

    Returns:
        The upscaler name, or an empty string if the file has no metadata at all.

    """
    metadata = read_png_metadata(srce_upscayl_file)

    upscaler = metadata.get(UPSCALER_KEY, "")
    if upscaler:
        return upscaler

    if UPSCAYL_MODEL_KEY in metadata:
        return str(Upscaler.UPSCAYL)
    if WAIFU2X_MODEL_KEY in metadata:
        return str(Upscaler.WAIFU2X)

    return ""
