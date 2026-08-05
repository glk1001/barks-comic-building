"""Tests for the decision to skip a page or upscayl it again.

The failure that matters is silent: calling a stale page current would leave it out of a
re-run started precisely to redo it. The library was upscayled with Upscayl and carries no
recipe at all, so "no recipe recorded" has to read as stale rather than as done.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from barks_fantagraphics.fanta_comics_info import FANTAGRAPHICS_UPSCAYLED_FIXES_DIRNAME
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from barks_comic_building.restore import upscale_image
from barks_comic_building.restore.upscale_image import (
    HAND_EDITED_DIRNAMES,
    Upscaler,
    check_upscaler_is_usable,
    upscale_image_file,
)
from barks_comic_building.restore.upscale_state import (
    RECIPE_ID_KEY,
    UPSCALE_DATE_KEY,
    UpscalePageState,
    get_upscale_page_status,
)

if TYPE_CHECKING:
    from pathlib import Path

CURRENT_RECIPE_ID = "aaaaaaaaaaaa"
OLD_RECIPE_ID = "bbbbbbbbbbbb"
UPSCALE_DATE = "2026-07-29T18:00:00+10:00"


def write_png(path: Path, metadata: dict[str, str] | None = None) -> Path:
    """Write a tiny png, optionally carrying BARKS metadata."""
    info = PngInfo()
    for key, value in (metadata or {}).items():
        info.add_text(f"BARKS:{key}", value)

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2)).save(str(path), pnginfo=info)

    return path


class Page:
    """The two files a page's upscale state is decided from."""

    def __init__(self, tmp_path: Path) -> None:
        self.srce = tmp_path / "srce.jpg"
        self.upscayl = tmp_path / "upscayl.png"

    def state(
        self, *, is_fixes_file: bool = False, is_hand_restored: bool = False
    ) -> UpscalePageState:
        return get_upscale_page_status(
            self.srce,
            self.upscayl,
            CURRENT_RECIPE_ID,
            is_fixes_file=is_fixes_file,
            is_hand_restored=is_hand_restored,
        ).state

    def write_all(self, recipe_id: str | None) -> None:
        write_png(self.srce)
        metadata = {RECIPE_ID_KEY: recipe_id, UPSCALE_DATE_KEY: UPSCALE_DATE} if recipe_id else None
        write_png(self.upscayl, metadata)


@pytest.fixture
def page(tmp_path: Path) -> Page:
    return Page(tmp_path)


class TestUpscalePageState:
    def test_no_srce_cannot_be_upscayled(self, page: Page) -> None:
        assert page.state() is UpscalePageState.NO_SRCE

    def test_no_output_is_missing(self, page: Page) -> None:
        write_png(page.srce)

        assert page.state() is UpscalePageState.MISSING

    def test_matching_recipe_is_current(self, page: Page) -> None:
        page.write_all(CURRENT_RECIPE_ID)

        assert page.state() is UpscalePageState.CURRENT

    def test_different_recipe_is_stale(self, page: Page) -> None:
        page.write_all(OLD_RECIPE_ID)

        assert page.state() is UpscalePageState.STALE

    def test_no_recipe_at_all_is_stale(self, page: Page) -> None:
        """Every page upscayled before provenance was kept, which is the whole library."""
        page.write_all(recipe_id=None)

        assert page.state() is UpscalePageState.STALE

    def test_unreadable_output_is_stale_not_current(self, page: Page) -> None:
        """A truncated write must never be mistaken for a finished page."""
        page.write_all(CURRENT_RECIPE_ID)
        page.upscayl.write_bytes(b"not a png")

        assert page.state() is UpscalePageState.STALE

    def test_a_symlinked_output_belongs_to_another_volume(self, page: Page, tmp_path: Path) -> None:
        """Collection titles borrow pages from other volumes by symlink.

        Queueing one would upscale it through the link, replacing that volume's page with
        an upscale of a different source image.
        """
        other_volume_page = write_png(tmp_path / "other" / "123.png")
        write_png(page.srce)
        page.upscayl.symlink_to(other_volume_page)

        assert page.state() is UpscalePageState.LINKED

    def test_a_symlink_is_linked_even_when_it_is_broken(self, page: Page, tmp_path: Path) -> None:
        """Writing would create the missing file at the far end, in the other volume."""
        write_png(page.srce)
        page.upscayl.symlink_to(tmp_path / "other" / "gone.png")

        assert page.state() is UpscalePageState.LINKED

    def test_the_date_is_read_back(self, page: Page) -> None:
        page.write_all(CURRENT_RECIPE_ID)

        status = get_upscale_page_status(
            page.srce,
            page.upscayl,
            CURRENT_RECIPE_ID,
            is_fixes_file=False,
            is_hand_restored=False,
        )

        assert status.upscale_date == UPSCALE_DATE
        assert status.recipe_id == CURRENT_RECIPE_ID


class TestAHandEditedPageIsNeverTheRunsToMake:
    """A fixes file replaces the upscayled page, so it is what a run would write over.

    It was made by hand and carries no recipe of ours, so every recipe test calls it
    stale - which is what had the batch run redo it, and destroy it, on every pass.
    """

    def test_a_fixes_page_is_fixes_not_stale(self, page: Page) -> None:
        page.write_all(recipe_id=None)

        assert page.state(is_fixes_file=True) is UpscalePageState.FIXES

    def test_a_fixes_page_stays_fixes_whatever_recipe_it_carries(self, page: Page) -> None:
        """Including the run's own recipe, stamped there by an earlier overwrite."""
        page.write_all(CURRENT_RECIPE_ID)

        assert page.state(is_fixes_file=True) is UpscalePageState.FIXES

    def test_an_added_fixes_page_with_no_srce_is_still_fixes(self, page: Page) -> None:
        """An ADDED page has no original scan; NO_SRCE happened to spare it, FIXES means it."""
        write_png(page.upscayl)

        assert page.state(is_fixes_file=True) is UpscalePageState.FIXES

    def test_a_borrowed_fixes_page_is_reported_as_linked(self, page: Page, tmp_path: Path) -> None:
        """A page can be both: a link standing here, pointing into another volume's fixes.

        Either answer skips it, so nothing is at risk; LINKED is reported because it names
        the volume the page belongs to, and counting it under FIXES would have the closing
        tally claim another volume's hand edits as this one's.
        """
        other_volume_fix = write_png(tmp_path / "other" / "123.png")
        write_png(page.srce)
        page.upscayl.symlink_to(other_volume_fix)

        assert page.state(is_fixes_file=True) is UpscalePageState.LINKED


class TestAHandRestoredPagesUpscaleFeedsNobody:
    """The upscayled page exists only as the restore's input.

    The restore leaves a hand-restored page alone, so making its upscale is four minutes
    and 25MB spent on a file no later stage opens.
    """

    def test_a_hand_restored_page_is_not_upscayled(self, page: Page) -> None:
        page.write_all(recipe_id=None)

        assert page.state(is_hand_restored=True) is UpscalePageState.HAND_RESTORED

    def test_it_stays_so_under_the_current_recipe(self, page: Page) -> None:
        page.write_all(CURRENT_RECIPE_ID)

        assert page.state(is_hand_restored=True) is UpscalePageState.HAND_RESTORED

    def test_a_missing_upscayl_is_still_not_made(self, page: Page) -> None:
        """MISSING is the state that would otherwise queue it on every single run."""
        write_png(page.srce)

        assert page.state(is_hand_restored=True) is UpscalePageState.HAND_RESTORED

    def test_a_fixes_page_that_is_also_hand_restored_is_reported_as_fixes(self, page: Page) -> None:
        """Volume 4's 227 is both. FIXES is the one that names a file at risk.

        HAND_RESTORED only says the output need not be made; FIXES says writing it would
        destroy a hand edit, which is the more urgent of the two to be told.
        """
        page.write_all(recipe_id=None)

        assert page.state(is_fixes_file=True, is_hand_restored=True) is UpscalePageState.FIXES


class TestNeedsUpscayling:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (UpscalePageState.CURRENT, False),
            (UpscalePageState.NO_SRCE, False),
            (UpscalePageState.LINKED, False),
            (UpscalePageState.FIXES, False),
            (UpscalePageState.HAND_RESTORED, False),
            (UpscalePageState.STALE, True),
            (UpscalePageState.MISSING, True),
        ],
    )
    def test_only_the_fixable_states_are_queued(
        self, state: UpscalePageState, *, expected: bool
    ) -> None:
        """Only the states an upscale can actually fix are queued.

        NO_SRCE must not be, because there is nothing to upscayl from - a run that queued
        it would fail the page on every attempt forever.
        """
        assert state.needs_upscayling is expected


class TestTheWriterRefusesToo:
    """The page state keeps these pages out of a run; this keeps them safe anyway.

    A guard in only one of the two places would leave `single_upscayl` and
    `directory_upscayl` able to do the damage.
    """

    def test_upscaling_onto_a_symlink_is_refused(self, tmp_path: Path) -> None:
        other_volume_page = write_png(tmp_path / "other" / "123.png")
        before = other_volume_page.read_bytes()

        out_file = tmp_path / "500.png"
        out_file.symlink_to(other_volume_page)

        with pytest.raises(ValueError, match="symlink"):
            upscale_image_file(write_png(tmp_path / "srce.png"), out_file, 4)

        assert other_volume_page.read_bytes() == before

    @pytest.mark.parametrize("tree", HAND_EDITED_DIRNAMES)
    def test_upscaling_into_a_hand_edited_tree_is_refused(self, tmp_path: Path, tree: str) -> None:
        hand_edit = write_png(tmp_path / tree / "Vol. 4" / "images" / "045.png")
        before = hand_edit.read_bytes()

        with pytest.raises(ValueError, match="hand-edited"):
            upscale_image_file(write_png(tmp_path / "srce.png"), hand_edit, 4)

        assert hand_edit.read_bytes() == before

    def test_a_new_page_in_a_hand_edited_tree_is_refused_as_well(self, tmp_path: Path) -> None:
        """The tree is refused, not just the pages already in it."""
        out_file = (
            tmp_path / FANTAGRAPHICS_UPSCAYLED_FIXES_DIRNAME / "Vol. 4" / "images" / "999.png"
        )
        out_file.parent.mkdir(parents=True)

        with pytest.raises(ValueError, match="hand-edited"):
            upscale_image_file(write_png(tmp_path / "srce.png"), out_file, 4)

        assert not out_file.exists()

    def test_a_symlinked_volume_directory_does_not_hide_the_tree(self, tmp_path: Path) -> None:
        """Staged collections reach their pages through a symlinked volume directory."""
        real_volume = tmp_path / FANTAGRAPHICS_UPSCAYLED_FIXES_DIRNAME / "Vol. 4" / "images"
        hand_edit = write_png(real_volume / "045.png")
        before = hand_edit.read_bytes()

        staged = tmp_path / "staged"
        staged.symlink_to(real_volume, target_is_directory=True)

        with pytest.raises(ValueError, match="hand-edited"):
            upscale_image_file(write_png(tmp_path / "srce.png"), staged / "045.png", 4)

        assert hand_edit.read_bytes() == before


class TestRunLevelPreconditions:
    """Things true for every page or none belong before the loop, not inside it."""

    def test_a_missing_binary_is_checked_once_up_front(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(upscale_image, "WAIFU2X_BIN", tmp_path / "not-installed")
        with pytest.raises(FileNotFoundError, match="binary"):
            check_upscaler_is_usable(Upscaler.WAIFU2X, 4)

    def test_an_impossible_scale_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot scale"):
            check_upscaler_is_usable(Upscaler.UPSCAYL, 7)


class TestRunningTheBackend:
    """Neither backend reports progress, so what it prints only matters when it fails.

    Both streams have to reach the log: the "done" line goes to stdout and the device
    banner - which GPU was picked - goes to stderr, and losing either leaves a failed run
    with nothing to go on.
    """

    def run(self, script: str) -> None:
        upscale_image._run_upscaler(Upscaler.WAIFU2X, ["sh", "-c", script])  # noqa: SLF001

    def test_a_clean_run_says_nothing(self) -> None:
        self.run("echo 'in.png -> out.png done'")

    def test_both_streams_are_captured(self) -> None:
        with pytest.raises(RuntimeError) as exc:
            self.run("echo on-stdout; echo on-stderr >&2; exit 1")

        assert "on-stdout" in str(exc.value)
        assert "on-stderr" in str(exc.value)

    def test_the_exit_code_is_reported(self) -> None:
        with pytest.raises(RuntimeError, match="exit 3"):
            self.run("exit 3")

    def test_a_silent_failure_still_names_the_backend(self) -> None:
        with pytest.raises(RuntimeError, match="waifu2x failed"):
            self.run("exit 3")

    def test_a_flood_of_output_is_bounded(self) -> None:
        """A backend stuck in a loop must not fill memory with its complaints."""
        with pytest.raises(RuntimeError) as exc:
            self.run("for i in $(seq 500); do echo line-$i; done; exit 1")

        kept = str(exc.value).splitlines()[1:]
        assert len(kept) == upscale_image._MAX_KEPT_OUTPUT_LINES  # noqa: SLF001
        assert kept[-1] == "line-500"
