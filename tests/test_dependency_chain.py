"""Tests for the restore chain walk - the check that spent this repo's history dead.

A dest page is the end of a pipeline: original scan, upscayled, restored-svg, restored,
panel segments. Each stage is produced *from* the one after it, so timestamps must
decrease along the chain. An inversion means the thing derived from that stage is stale
and needs rebuilding.

The walk existed and was called, but the timestamp it compared was pinned to `0.0`, so
no inversion could ever be reported and the running source maximum stayed at zero for
every title - which silently killed two further checks downstream that compared against
it. Nothing failed; the report simply said the tree was clean.

So the assertion that matters most here is the one that would have caught that: a chain
carrying the missing-stage sentinel must report an inversion, whatever else is true. The
rest pins the ordering rules a reader would otherwise have to infer from the walk.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from barks_fantagraphics.pages import SrceDependency

from barks_comic_building.build.comics_integrity import dating_dependencies
from barks_comic_building.build.utils import MaxTimestamp, walk_srce_dependency_chain

# Fixed epoch seconds. No file is ever created - the walk reads `dependency.timestamp`
# and never stats, which is the whole point of having it take the dependencies.
OLDEST = 1_600_000_000.0
OLD = 1_700_000_000.0
NEW = 1_800_000_000.0
NEWER = 1_900_000_000.0

# `get_restored_srce_dependencies` uses -1 for a pipeline stage whose file is not on disk.
MISSING_STAGE = -1.0

DEST = Path("/comics/dest/001.jpg")
SEGMENTS = Path("/fanta/panel-segments/001.json")
RESTORED = Path("/fanta/restored/001.png")
UPSCAYLED = Path("/fanta/upscayled/001.png")
ORIGINAL = Path("/fanta/original/001.jpg")
INI_FILE = Path("/reader-repo/data/story-titles/A Title.ini")
INSET_FILE = Path("/comics/Barks Panels Pngs/Insets/A Title.png")
BOUNDS_OVERRIDE = Path("/fanta/fixes/images/bounded/001.jpg")


def chained(*stages: tuple[Path, float]) -> list[SrceDependency]:
    """Build a restore chain, latest pipeline stage first.

    Args:
        stages: The `(file, timestamp)` pairs, in the order the pipeline produced them
            reversed - as `get_restored_srce_dependencies` returns them.

    Returns:
        The chain, every entry marked as derived from the next.

    """
    return [SrceDependency(file, timestamp, independent=False) for file, timestamp in stages]


class TestAConsistentChain:
    def test_a_chain_older_than_its_dest_page_reports_nothing(self) -> None:
        # Each stage older than the thing built from it, and the dest page newest of all.
        chain = chained((SEGMENTS, NEW), (RESTORED, OLD), (UPSCAYLED, OLDEST))

        result = walk_srce_dependency_chain(chain, DEST, NEWER, None, is_a_comic=True)

        assert result.stale_pairs == []

    def test_an_empty_chain_reports_nothing(self) -> None:
        # A blank page has no dependencies at all.
        result = walk_srce_dependency_chain([], DEST, NEW, None, is_a_comic=True)

        assert result.stale_pairs == []
        assert result.max_srce is None

    def test_the_newest_dependency_becomes_the_maximum(self) -> None:
        chain = chained((SEGMENTS, OLD), (RESTORED, NEW), (UPSCAYLED, OLDEST))

        result = walk_srce_dependency_chain(chain, DEST, NEWER, None, is_a_comic=True)

        assert result.max_srce == MaxTimestamp(RESTORED, NEW)


class TestAnInvertedChain:
    def test_a_stage_newer_than_the_dest_page_is_reported_against_it(self) -> None:
        # Panel segments regenerated after the page was built: the page needs rebuilding.
        chain = chained((SEGMENTS, NEWER), (RESTORED, OLD))

        result = walk_srce_dependency_chain(chain, DEST, NEW, None, is_a_comic=True)

        assert result.stale_pairs == [(SEGMENTS, DEST)]

    def test_a_stage_newer_than_the_stage_built_from_it_is_reported_mid_chain(self) -> None:
        # The dest page is fine and so is the original end of the chain; it is the panel
        # segments that predate the restored image they were computed from, so it is the
        # segments that need regenerating. Reported as the pair, so the message names
        # both halves rather than just the file that is too old.
        chain = chained((SEGMENTS, OLD), (RESTORED, NEW), (UPSCAYLED, OLDEST))

        result = walk_srce_dependency_chain(chain, DEST, NEWER, None, is_a_comic=True)

        assert result.stale_pairs == [(RESTORED, SEGMENTS)]

    def test_every_inversion_in_one_chain_is_reported(self) -> None:
        chain = chained((SEGMENTS, NEWER), (RESTORED, OLDEST), (UPSCAYLED, NEW))

        result = walk_srce_dependency_chain(chain, DEST, OLD, None, is_a_comic=True)

        assert result.stale_pairs == [(SEGMENTS, DEST), (UPSCAYLED, RESTORED)]


class TestTheMissingStageSentinel:
    """A stage that is not on disk is always an inversion.

    This is the assertion that would have caught the dead check: with the timestamp
    pinned to `0.0`, the sign test could never be true, so a missing restored image
    reported nothing at all.
    """

    def test_a_missing_stage_is_an_inversion_however_new_the_dest_page_is(self) -> None:
        chain = chained((SEGMENTS, MISSING_STAGE))

        result = walk_srce_dependency_chain(chain, DEST, NEWER, None, is_a_comic=True)

        assert result.stale_pairs == [(SEGMENTS, DEST)]

    def test_a_missing_stage_never_becomes_the_maximum(self) -> None:
        chain = chained((SEGMENTS, MISSING_STAGE), (RESTORED, OLD))

        result = walk_srce_dependency_chain(chain, DEST, NEWER, None, is_a_comic=True)

        assert result.max_srce == MaxTimestamp(RESTORED, OLD)

    def test_a_missing_stage_is_reported_once_not_twice(self) -> None:
        # The stage after a missing one used to be paired against it as well, because the
        # sentinel is lower than any real timestamp. Both pairs render to the same line -
        # `File "<SEGMENTS>" is missing.` - since naming the absent file is all either pair
        # can say, so one missing file was logged twice and counted twice in the tally.
        chain = chained((SEGMENTS, MISSING_STAGE), (RESTORED, OLD))

        result = walk_srce_dependency_chain(chain, DEST, NEWER, None, is_a_comic=True)

        assert result.stale_pairs == [(SEGMENTS, DEST)]

    def test_consecutive_missing_stages_are_each_reported(self) -> None:
        # Not-reporting-twice must not become not-reporting: each absent file is a separate
        # finding naming a different file, which is the real Vol. 8 case (the whole tail of
        # the chain gone).
        chain = chained((SEGMENTS, MISSING_STAGE), (RESTORED, MISSING_STAGE), (UPSCAYLED, OLD))

        result = walk_srce_dependency_chain(chain, DEST, NEWER, None, is_a_comic=True)

        assert result.stale_pairs == [(SEGMENTS, DEST), (RESTORED, SEGMENTS)]

    def test_the_walk_resumes_after_a_missing_stage(self) -> None:
        # Skipping the pair must not skip the comparison: the stages after the missing one
        # still grade against each other, so an inversion further down is still found.
        chain = chained((SEGMENTS, MISSING_STAGE), (RESTORED, OLD), (UPSCAYLED, NEW))

        result = walk_srce_dependency_chain(chain, DEST, NEWER, None, is_a_comic=True)

        assert result.stale_pairs == [(SEGMENTS, DEST), (UPSCAYLED, RESTORED)]


class TestIndependentDependencies:
    """The ini file, the intro inset and a hand-drawn panel bounds fix.

    None of these can be a chain inversion, but for two different reasons. Nothing is
    derived from the ini or the inset at all. The bounds override *is* derived from -
    the panel segments are computed from it - but the chain here is linear and that
    dependency is a fork: the segments come from the override *and* the restored page.
    Putting the override in the chain would make the restored page compare against it
    instead of against the segments, masking a real inversion whenever the override is
    the newest of the three. `panel_segments_are_stale` grades that fork instead.

    Either way they are still inputs, and an edited ini is the ordinary reason a built
    comic goes stale.
    """

    def test_an_independent_dependency_is_never_an_inversion(self) -> None:
        chain = [SrceDependency(INI_FILE, NEWER, independent=True)]

        result = walk_srce_dependency_chain(chain, DEST, OLD, None, is_a_comic=True)

        assert result.stale_pairs == []

    def test_an_independent_dependency_still_raises_the_maximum(self) -> None:
        # This is what makes a title's info files stale after an ini edit.
        chain = [SrceDependency(INI_FILE, NEWER, independent=True)]

        result = walk_srce_dependency_chain(chain, DEST, OLD, None, is_a_comic=True)

        assert result.max_srce == MaxTimestamp(INI_FILE, NEWER)

    def test_a_bounds_override_does_not_displace_the_segments_in_the_chain(self) -> None:
        # The regression that keeps the override independent. With it chained between the
        # segments and the restored page, the restored page would compare against the
        # override (NEWEST, so no inversion) instead of against the segments, and the
        # segments being older than the page they were computed from would go unreported.
        chain = [
            SrceDependency(SEGMENTS, OLDEST, independent=False),
            SrceDependency(BOUNDS_OVERRIDE, NEWER, independent=True),
            SrceDependency(RESTORED, NEW, independent=False),
        ]

        result = walk_srce_dependency_chain(chain, DEST, NEWER, None, is_a_comic=True)

        assert result.stale_pairs == [(RESTORED, SEGMENTS)]

    def test_an_independent_dependency_does_not_break_the_chain_around_it(self) -> None:
        # It is skipped for chaining purposes, so the stages either side still compare
        # against each other rather than against the ini file.
        chain = [
            SrceDependency(SEGMENTS, OLDEST, independent=False),
            SrceDependency(INI_FILE, NEWER, independent=True),
            SrceDependency(RESTORED, NEW, independent=False),
        ]

        result = walk_srce_dependency_chain(chain, DEST, NEWER, None, is_a_comic=True)

        assert result.stale_pairs == [(RESTORED, SEGMENTS)]


class TestNonComicTitles:
    def test_a_non_comic_reports_no_inversions(self) -> None:
        # The articles have no restore pipeline for their pages to be inconsistent with.
        chain = chained((SEGMENTS, NEWER), (RESTORED, MISSING_STAGE))

        result = walk_srce_dependency_chain(chain, DEST, OLD, None, is_a_comic=False)

        assert result.stale_pairs == []

    def test_a_non_comic_still_raises_the_maximum(self) -> None:
        chain = chained((SEGMENTS, NEWER))

        result = walk_srce_dependency_chain(chain, DEST, OLD, None, is_a_comic=False)

        assert result.max_srce == MaxTimestamp(SEGMENTS, NEWER)


class TestADependencyInsideAZip:
    """Only the intro inset can live in a zip, and it is always independent.

    That fact used to be relied on without being stated: the chain's tuple type admitted
    `zipfile.Path`, two type-checker suppressions papered over it, and a bare `assert`
    380 lines away caught the case that could not happen. Narrowing here says it once.
    """

    @staticmethod
    def _inset(tmp_path: Path) -> zipfile.Path:
        """Make a real `zipfile.Path` to an inset image inside an archive."""
        archive = tmp_path / "insets.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("inset.png", b"")

        return zipfile.Path(archive, "inset.png")

    def test_a_zipped_dependency_never_enters_the_chain(self, tmp_path: Path) -> None:
        chain = [SrceDependency(self._inset(tmp_path), NEWER, independent=True)]

        result = walk_srce_dependency_chain(chain, DEST, OLD, None, is_a_comic=True)

        assert result.stale_pairs == []

    def test_a_zipped_dependency_still_raises_the_maximum(self, tmp_path: Path) -> None:
        inset = self._inset(tmp_path)

        result = walk_srce_dependency_chain(
            [SrceDependency(inset, NEWER, independent=True)], DEST, OLD, None, is_a_comic=True
        )

        assert result.max_srce == MaxTimestamp(inset, NEWER)


class TestWhatIsAllowedToDateABuild:
    """The ini file's timestamp must not, and everything else's must.

    An ini edit is caught by comparing its *hash* against the one recorded at build time,
    which is exact. Its mtime says nothing: the ini files are git-tracked in a different
    repository from the comics, so any checkout rewrites every one of them. Counting that
    as staleness produced 90% of a real tree's 3323 findings from a single bulk mtime
    bump in which no ini's content had changed at all.
    """

    def test_the_ini_file_is_dropped(self) -> None:
        dependencies = [
            SrceDependency(INI_FILE, NEWER, independent=True),
            SrceDependency(INSET_FILE, OLD, independent=True),
        ]

        kept = dating_dependencies(dependencies, INI_FILE)

        assert [dependency.file for dependency in kept] == [INSET_FILE]

    def test_the_ini_file_therefore_cannot_make_a_build_look_stale(self) -> None:
        # The finding this removes: a zip older than an ini whose content never changed.
        dependencies = [SrceDependency(INI_FILE, NEWER, independent=True)]

        result = walk_srce_dependency_chain(
            dating_dependencies(dependencies, INI_FILE), DEST, OLD, None, is_a_comic=True
        )

        assert result.max_srce is None

    def test_the_intro_inset_still_dates_the_build(self) -> None:
        # A content file under the comics root, not in git, and nothing hashes it - so an
        # edit to it really does mean the title page needs rebuilding.
        dependencies = [SrceDependency(INSET_FILE, NEWER, independent=True)]

        result = walk_srce_dependency_chain(
            dating_dependencies(dependencies, INI_FILE), DEST, OLD, None, is_a_comic=True
        )

        assert result.max_srce == MaxTimestamp(INSET_FILE, NEWER)

    def test_the_restore_chain_is_untouched(self) -> None:
        dependencies = chained((SEGMENTS, NEW), (RESTORED, OLD))

        assert dating_dependencies(dependencies, INI_FILE) == dependencies

    def test_dropping_is_by_path_not_by_independence(self) -> None:
        # Every independent dependency would be the wrong rule - it would take the inset
        # and the hand-drawn panel bounds fix with it.
        panel_bounds = Path("/fanta/fixes/bounded/001.json")
        dependencies = [SrceDependency(panel_bounds, NEWER, independent=True)]

        kept = dating_dependencies(dependencies, INI_FILE)

        assert [dependency.file for dependency in kept] == [panel_bounds]


class TestTheRunningMaximum:
    def test_a_maximum_from_an_earlier_page_is_carried_in(self) -> None:
        # The maximum accumulates across every page of a title, so a later page must not
        # lower it.
        carried = MaxTimestamp(ORIGINAL, NEWER)

        result = walk_srce_dependency_chain(
            chained((SEGMENTS, OLD)), DEST, NEW, carried, is_a_comic=True
        )

        assert result.max_srce == carried

    @pytest.mark.parametrize("dest_timestamp", [OLDEST, OLD, NEW, NEWER])
    def test_the_dest_page_never_enters_the_maximum(self, dest_timestamp: float) -> None:
        # `max_srce` is the newest *input*. Folding the dest page into it would compare
        # the page against itself and never report anything.
        result = walk_srce_dependency_chain(
            chained((SEGMENTS, OLDEST)), DEST, dest_timestamp, None, is_a_comic=True
        )

        assert result.max_srce == MaxTimestamp(SEGMENTS, OLDEST)
