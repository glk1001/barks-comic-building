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

    Mirrors a real member: an original-scan jpg plus one optional later artifact,
    each a `(link, source)` pair pointing from the collection into the member's own
    volume.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.srce_jpg = tmp_path / "vol" / "078.jpg"
        self.srce_png = tmp_path / "vol" / "078.png"
        self.link_jpg = tmp_path / "collection" / "519.jpg"
        self.link_png = tmp_path / "collection" / "519.png"
        for path in (self.srce_jpg, self.link_jpg):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.srce_jpg.touch()

    @property
    def links(self) -> list[tuple[Path, Path]]:
        return [(self.link_jpg, self.srce_jpg), (self.link_png, self.srce_png)]

    def stage_correctly(self) -> None:
        self.link_jpg.symlink_to(self.srce_jpg)

    def check(self) -> int:
        return check_collection_staged_links(Titles.ALL_ONE_PAGERS, {MEMBER: self.links})


@pytest.fixture
def member(tmp_path: Path) -> StagedMember:
    return StagedMember(tmp_path)


class TestConsistentStaging:
    def test_a_correctly_staged_member_passes(self, member: StagedMember) -> None:
        member.stage_correctly()

        assert member.check() == 0

    def test_a_stage_not_yet_run_is_not_an_error(self, member: StagedMember) -> None:
        # The .png source does not exist, so there is nothing to link - outstanding
        # work rather than a fault, and not this gate's business.
        member.stage_correctly()

        assert not member.link_png.exists()
        assert member.check() == 0

    def test_an_artifact_produced_in_the_collection_is_not_an_error(
        self, member: StagedMember
    ) -> None:
        # `barks-batch-upscayl --title "All One-Pagers"` writes a real file for a stage
        # the member's own volume never had. Nothing upstream to have diverged from.
        member.stage_correctly()
        member.link_png.touch()

        assert not member.srce_png.exists()
        assert member.check() == 0


class TestStagingFaults:
    def test_a_dangling_link_is_caught(self, member: StagedMember) -> None:
        member.stage_correctly()
        member.srce_jpg.unlink()

        assert member.link_jpg.is_symlink()
        assert member.check() == 1

    def test_a_link_pointing_at_the_wrong_source_is_caught(self, member: StagedMember) -> None:
        # The location table gained an entry and every later member's page shifted,
        # but nothing was restaged - so this page still points at the earlier member's scan.
        other_scan = member.srce_jpg.with_name("079.jpg")
        other_scan.touch()
        member.link_jpg.symlink_to(other_scan)

        assert member.link_jpg.exists(), "the wrong source still resolves, which is the point"
        assert member.check() == 1

    def test_a_diverged_copy_is_caught(self, member: StagedMember) -> None:
        # A real file whose upstream source also exists: it will not pick up a
        # re-restore of that source.
        member.stage_correctly()
        member.srce_png.touch()
        member.link_png.touch()

        assert member.check() == 1

    def test_a_member_with_no_staged_scan_is_caught(self, member: StagedMember) -> None:
        # A location was authored but the stager was never run, so the collection has
        # no image for this member at all.
        assert not member.link_jpg.exists()
        assert member.check() == 1

    def test_an_artifact_that_exists_upstream_but_was_never_staged_is_caught(
        self, member: StagedMember
    ) -> None:
        # The member has been restored since it was staged, so the artifact exists in
        # its own volume - but no link was ever made, so the build cannot see it. The
        # scan-only check passed this, because the scan itself is staged correctly.
        member.stage_correctly()
        member.srce_png.touch()

        assert not member.link_png.exists()
        assert member.check() == 1
