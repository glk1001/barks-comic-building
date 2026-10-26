"""Tests for the integrity gate over the synthetic collections' staged links.

Every other integrity check asks whether a file exists and whether it is newer than
another file. Neither question can catch a staged link pointing at the wrong source:
the page built from it is a valid image, just of the wrong gag, and its timestamps
are perfectly consistent. So each failure mode this gate exists for is constructed
here - a check that has never been shown to fire is not a check.

The members' pictures are real images, because one of those failure modes is a real file
holding the wrong picture. Each gag is a seeded pattern of grey blocks: two seeds are as
unlike as two different gags, and a lightened copy is as alike as a page and its restore.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, cast

import pytest
from barks_fantagraphics.barks_titles import Titles
from PIL import Image

from barks_comic_building.build import comics_integrity
from barks_comic_building.build.comics_integrity import (
    ComicsIntegrityChecker,
    check_collection_staged_links,
    find_misplaced_files,
)

if TYPE_CHECKING:
    from pathlib import Path

    from barks_fantagraphics.comics_database import ComicsDatabase

MEMBER = Titles.BIRD_WATCHING
OTHER_MEMBER = Titles.HORSESHOE_LUCK

MEMBER_GAG = 1
OTHER_GAG = 2
UNSTAGED_GAG = 3

# The blocks a gag is drawn in, and the size each is written at. Not to scale - only the
# layout matters to the check, which reduces every page to the same small thumbnail.
_GAG_BLOCKS = (8, 11)
_PAGE_SIZE = (80, 110)


def write_gag(path: Path, gag: int, *, restored: bool = False) -> Path:
    """Write one gag's page; ``restored`` lightens it, as the restore changes its tones."""
    rng = random.Random(gag)
    blocks = Image.new("L", _GAG_BLOCKS)
    blocks.putdata([rng.randrange(256) for _ in range(_GAG_BLOCKS[0] * _GAG_BLOCKS[1])])
    page = blocks.resize(_PAGE_SIZE, Image.Resampling.NEAREST)
    if restored:
        page = page.point(lambda value: 80 + value * 6 // 10)

    path.parent.mkdir(parents=True, exist_ok=True)
    page.convert("RGB").save(path)

    return path


class StagedMember:
    """One collection member's staged artifacts, as the stagers describe them.

    Mirrors a real member: the original scan plus one optional later artifact, each a
    `(link, source)` pair pointing from the collection into the member's own volume. The
    scan comes first, as both stagers build it - that order is the contract
    `original_scan_slot` reads, and `scan_ext` is what makes it worth pinning.
    """

    def __init__(
        self,
        tmp_path: Path,
        scan_ext: str = ".jpg",
        *,
        page: str = "078",
        collection_page: str = "519",
        gag: int = MEMBER_GAG,
    ) -> None:
        # The scan slot takes its source's extension, so a member whose volume holds a
        # `.png` fix is staged as "519.png" - see `staged_link_for`.
        self.gag = gag
        self.srce_scan = tmp_path / "vol" / f"{page}{scan_ext}"
        self.srce_artifact = tmp_path / "vol" / f"{page}.upscayled.png"
        self.link_scan = tmp_path / "collection" / f"{collection_page}{scan_ext}"
        self.link_artifact = tmp_path / "collection" / f"{collection_page}.upscayled.png"
        self.link_scan.parent.mkdir(parents=True, exist_ok=True)
        write_gag(self.srce_scan, gag)

    @property
    def links(self) -> list[tuple[Path, Path]]:
        # Scan first, as both stagers build it - `original_scan_slot` reads that order.
        return [(self.link_scan, self.srce_scan), (self.link_artifact, self.srce_artifact)]

    def stage_correctly(self) -> None:
        self.link_scan.symlink_to(self.srce_scan)

    def write_artifact_in_place(self, gag: int | None = None) -> None:
        """Write the artifact as a real file in its slot, of ``gag`` or its own page."""
        write_gag(self.link_artifact, self.gag if gag is None else gag, restored=True)

    def check(self) -> int:
        return check_collection_staged_links(Titles.ALL_ONE_PAGERS, {MEMBER: self.links})


@pytest.fixture
def member(tmp_path: Path) -> StagedMember:
    return StagedMember(tmp_path)


class TestConsistentStaging:
    def test_a_correctly_staged_member_passes(self, member: StagedMember) -> None:
        member.stage_correctly()

        assert member.check() == 0

    def test_a_scan_staged_under_png_passes(self, tmp_path: Path) -> None:
        # A member whose volume grew a `.png` fix is staged as "519.png". The check used
        # to find the scan by a `.jpg` suffix, so it reported this correctly staged
        # member as having no scan at all - and restaging could not clear it, because
        # restaging recreates the same `.png` slot.
        member = StagedMember(tmp_path, scan_ext=".png")
        member.stage_correctly()

        assert member.link_scan.suffix == ".png", "the scan slot took its source's extension"
        assert member.check() == 0

    def test_a_stage_not_yet_run_is_not_an_error(self, member: StagedMember) -> None:
        # The .png source does not exist, so there is nothing to link - outstanding
        # work rather than a fault, and not this gate's business.
        member.stage_correctly()

        assert not member.link_artifact.exists()
        assert member.check() == 0

    def test_an_artifact_produced_in_the_collection_is_not_an_error(
        self, member: StagedMember
    ) -> None:
        # `barks-batch-upscayl --title "All One-Pagers"` writes a real file for a stage
        # the member's own volume never had. Nothing upstream to have diverged from.
        member.stage_correctly()
        member.write_artifact_in_place()

        assert not member.srce_artifact.exists()
        assert member.check() == 0


class TestStagingFaults:
    def test_a_dangling_link_is_caught(self, member: StagedMember) -> None:
        member.stage_correctly()
        member.srce_scan.unlink()

        assert member.link_scan.is_symlink()
        assert member.check() == 1

    def test_a_link_pointing_at_the_wrong_source_is_caught(self, member: StagedMember) -> None:
        # The location table gained an entry and every later member's page shifted,
        # but nothing was restaged - so this page still points at the earlier member's scan.
        other_scan = member.srce_scan.with_name("079.jpg")
        other_scan.touch()
        member.link_scan.symlink_to(other_scan)

        assert member.link_scan.exists(), "the wrong source still resolves, which is the point"
        assert member.check() == 1

    def test_a_diverged_copy_is_caught(self, member: StagedMember) -> None:
        # A real file whose upstream source also exists: it will not pick up a
        # re-restore of that source.
        member.stage_correctly()
        write_gag(member.srce_artifact, member.gag, restored=True)
        member.write_artifact_in_place()

        assert member.check() == 1

    def test_a_member_with_no_staged_scan_is_caught(self, member: StagedMember) -> None:
        # A location was authored but the stager was never run, so the collection has
        # no image for this member at all.
        assert not member.link_scan.exists()
        assert member.check() == 1

    def test_an_artifact_that_exists_upstream_but_was_never_staged_is_caught(
        self, member: StagedMember
    ) -> None:
        # The member has been restored since it was staged, so the artifact exists in
        # its own volume - but no link was ever made, so the build cannot see it. The
        # scan-only check passed this, because the scan itself is staged correctly.
        member.stage_correctly()
        member.srce_artifact.touch()

        assert not member.link_artifact.exists()
        assert member.check() == 1


class TestRealFilesAreTheirMembersPage:
    """A real file in a slot must be a picture of the member staged there.

    Member *i* is page ``base + i``, so locating, adding or reordering a member renumbers
    every later page. Links are restaged at the new numbers; a real file is not, and stays
    under a number that is now another member's page. All One-Pagers' slots 616-627 held
    twelve other gags' upscales and restores that way for three months, through every
    other check here.
    """

    @pytest.fixture
    def other(self, tmp_path: Path) -> StagedMember:
        other = StagedMember(tmp_path, page="079", collection_page="520", gag=OTHER_GAG)
        other.stage_correctly()

        return other

    @staticmethod
    def links_by_title(
        member: StagedMember, other: StagedMember
    ) -> dict[Titles, list[tuple[Path, Path]]]:
        return {MEMBER: member.links, OTHER_MEMBER: other.links}

    def test_a_restore_of_the_members_own_page_passes(
        self, member: StagedMember, other: StagedMember
    ) -> None:
        member.stage_correctly()
        member.write_artifact_in_place()

        assert find_misplaced_files(self.links_by_title(member, other)) == []

    def test_another_members_page_is_caught_and_named(
        self, member: StagedMember, other: StagedMember
    ) -> None:
        # Written while the other member was numbered 519, before a renumbering moved it.
        member.stage_correctly()
        member.write_artifact_in_place(OTHER_GAG)

        [found] = find_misplaced_files(self.links_by_title(member, other))

        assert (found.title, found.path) == (MEMBER, member.link_artifact)
        assert found.owner == OTHER_MEMBER
        assert found.owner_scan_slot == other.link_scan, "names the page it belongs on"

    def test_another_members_page_fails_the_gate(
        self, member: StagedMember, other: StagedMember
    ) -> None:
        member.stage_correctly()
        member.write_artifact_in_place(OTHER_GAG)

        links_by_title = self.links_by_title(member, other)
        assert check_collection_staged_links(Titles.ALL_ONE_PAGERS, links_by_title) == 1

    def test_the_gate_can_leave_the_content_out(
        self, member: StagedMember, other: StagedMember
    ) -> None:
        member.stage_correctly()
        member.write_artifact_in_place(OTHER_GAG)

        links_by_title = self.links_by_title(member, other)
        assert (
            check_collection_staged_links(
                Titles.ALL_ONE_PAGERS, links_by_title, check_content=False
            )
            == 0
        )

    def test_a_page_of_no_member_is_caught_without_an_owner(
        self, member: StagedMember, other: StagedMember
    ) -> None:
        member.stage_correctly()
        member.write_artifact_in_place(UNSTAGED_GAG)

        [found] = find_misplaced_files(self.links_by_title(member, other))

        assert found.owner is None

    def test_an_unreadable_real_file_is_caught(
        self, member: StagedMember, other: StagedMember
    ) -> None:
        member.stage_correctly()
        member.link_artifact.touch()

        [found] = find_misplaced_files(self.links_by_title(member, other))

        assert found.path == member.link_artifact
        assert "could not be compared" in found.detail

    def test_a_link_is_not_judged_by_its_picture(
        self, member: StagedMember, other: StagedMember
    ) -> None:
        # Where a link points is graded on its own, by the wrong-source check.
        member.stage_correctly()
        member.link_artifact.symlink_to(other.srce_scan)

        assert find_misplaced_files(self.links_by_title(member, other)) == []

    def test_the_svg_png_is_not_judged_by_its_picture(
        self, member: StagedMember, other: StagedMember, tmp_path: Path
    ) -> None:
        # Line art matches its scan too loosely to be held to the same threshold.
        member.stage_correctly()
        svg_png = write_gag(tmp_path / "collection" / "519.svg.png", OTHER_GAG)
        links = [*member.links, (svg_png, tmp_path / "vol" / "078.svg.png")]

        assert find_misplaced_files({MEMBER: links, OTHER_MEMBER: other.links}) == []


class TestWhichRunsCheckSlotContent:
    """The content check decodes every real upscale - about 30s - so it is scoped.

    It runs for a collection the run covers, and not otherwise: a run over volume 5 cannot
    have put a wrong file in a collection slot, and has no reason to wait for one.
    """

    @staticmethod
    def content_checked(
        monkeypatch: pytest.MonkeyPatch, titles: list[str], *, check_slot_content: bool = True
    ) -> dict[Titles, bool]:
        """Return, per collection, whether a run over ``titles`` checks its slot content."""
        asked: dict[Titles, bool] = {}

        def record(collection: Titles, _links: object, *, check_content: bool = True) -> int:
            asked[collection] = check_content
            return 0

        monkeypatch.setattr(comics_integrity, "get_one_pager_staged_links", lambda _db: {})
        monkeypatch.setattr(comics_integrity, "get_cover_staged_links", lambda _db: {})
        monkeypatch.setattr(comics_integrity, "check_collection_staged_links", record)
        checker = ComicsIntegrityChecker(
            cast("ComicsDatabase", object()),
            no_check_for_unexpected_files=False,
            no_check_symlinks=False,
            check_slot_content=check_slot_content,
        )
        assert checker.check_staged_collection_links(titles) == 0

        return asked

    def test_a_run_over_every_title_checks_both_collections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self.content_checked(monkeypatch, []) == {
            Titles.ALL_ONE_PAGERS: True,
            Titles.ALL_COVERS: True,
        }

    def test_a_run_including_one_collection_checks_only_that_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # What `--volume 1` comes to: its stories plus "All One-Pagers".
        titles = ["All One-Pagers", "Donald Duck Finds Pirate Gold"]

        assert self.content_checked(monkeypatch, titles) == {
            Titles.ALL_ONE_PAGERS: True,
            Titles.ALL_COVERS: False,
        }

    def test_a_run_over_no_collection_checks_neither(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self.content_checked(monkeypatch, ["Bird Watching"]) == {
            Titles.ALL_ONE_PAGERS: False,
            Titles.ALL_COVERS: False,
        }

    def test_the_flag_turns_it_off_for_every_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self.content_checked(monkeypatch, [], check_slot_content=False) == {
            Titles.ALL_ONE_PAGERS: False,
            Titles.ALL_COVERS: False,
        }
