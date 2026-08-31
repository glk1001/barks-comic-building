"""Tests for the integrity gate over the synthetic collections' staged links.

Every other integrity check asks whether a file exists and whether it is newer than
another file. Neither question can catch a staged link pointing at the wrong source:
the page built from it is a valid image, just of the wrong gag, and its timestamps
are perfectly consistent. So each failure mode this gate exists for is constructed
here - a check that has never been shown to fire is not a check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from barks_fantagraphics.barks_titles import Titles

from barks_comic_building.build.comics_integrity import check_collection_staged_links

if TYPE_CHECKING:
    from pathlib import Path

MEMBER = Titles.BIRD_WATCHING


class StagedMember:
    """One collection member's staged artifacts, as the stagers describe them.

    Mirrors a real member: the original scan plus one optional later artifact, each a
    `(link, source)` pair pointing from the collection into the member's own volume. The
    scan comes first, as both stagers build it - that order is the contract
    `original_scan_slot` reads, and `scan_ext` is what makes it worth pinning.
    """

    def __init__(self, tmp_path: Path, scan_ext: str = ".jpg") -> None:
        # The scan slot takes its source's extension, so a member whose volume holds a
        # `.png` fix is staged as "519.png" - see `staged_link_for`.
        self.srce_scan = tmp_path / "vol" / f"078{scan_ext}"
        self.srce_artifact = tmp_path / "vol" / "078.upscayled.png"
        self.link_scan = tmp_path / "collection" / f"519{scan_ext}"
        self.link_artifact = tmp_path / "collection" / "519.upscayled.png"
        for path in (self.srce_scan, self.link_scan):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.srce_scan.touch()

    @property
    def links(self) -> list[tuple[Path, Path]]:
        # Scan first, as both stagers build it - `original_scan_slot` reads that order.
        return [(self.link_scan, self.srce_scan), (self.link_artifact, self.srce_artifact)]

    def stage_correctly(self) -> None:
        self.link_scan.symlink_to(self.srce_scan)

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
        member.link_artifact.touch()

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
        member.srce_artifact.touch()
        member.link_artifact.touch()

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
