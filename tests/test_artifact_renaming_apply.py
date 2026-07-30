"""Tests for the half of the artifact rename fix that touches the disk.

`test_artifact_renaming.py` covers the ordering argument - that no rename ever clobbers a
live path. This covers what happens either side of that: the classification that decides
what to rename, the guard that refuses to overwrite, the recovery of a run killed
half-way, and the promise that a dry run changes nothing.

Every one of these protects a built comic, and a built comic costs a full rebuild to
recreate. `os.rename` silently replaces an existing file on POSIX, so the destination
guard is the only thing between a modelling error and a destroyed archive - and a dry run
that quietly renamed something would be worse than no dry run at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from barks_comic_building.build import artifact_renaming
from barks_comic_building.build.artifact_renaming import (
    TEMP_SUFFIX,
    ActualArtifacts,
    ArtifactFix,
    ArtifactKind,
    Disposition,
    ExpectedArtifacts,
    RenameConflictError,
    RenamePlan,
    RenameStep,
    SymlinkFix,
    _check_expected_paths_are_distinct,
    _plan_renames,
    _plan_symlinks,
    _safe_rename,
    apply_rename_plan,
    recover_interrupted_renames,
)

if TYPE_CHECKING:
    from pathlib import Path


# A leftover in each of the two recovery roots.
BOTH_ROOTS = 2


def touch(path: Path) -> Path:
    """Create an empty file, making its parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()

    return path


def expected_for(key: str, root: Path, number: int) -> ExpectedArtifacts:
    """Make one title's expected artifact paths under `root`.

    Args:
        key: The title's match key.
        root: The library root.
        number: The chronological number the artifacts should carry.

    Returns:
        The expected paths.

    """
    return ExpectedArtifacts(
        story_title=key,
        key=key,
        dest_dir=root / "dirs" / f"{number:03d} {key}",
        zip_file=root / "zips" / f"{number:03d} {key}.cbz",
        series_symlink=root / "series" / "Donald Duck" / f"{number:03d} {key}.cbz",
        year_symlink=root / "years" / "1949" / f"{number:03d} {key}.cbz",
    )


@pytest.fixture
def chrono_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Point the module's two recovery roots at empty directories under `tmp_path`."""
    dirs_root = tmp_path / "dirs"
    zips_root = tmp_path / "zips"
    dirs_root.mkdir(parents=True, exist_ok=True)
    zips_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(artifact_renaming, "THE_CHRONOLOGICAL_DIRS_DIR", dirs_root)
    monkeypatch.setattr(artifact_renaming, "THE_CHRONOLOGICAL_DIR", zips_root)

    return dirs_root, zips_root


class TestSafeRename:
    """The guard that stands between a modelling error and a destroyed comic."""

    def test_a_rename_onto_an_existing_file_is_refused(self, tmp_path: Path) -> None:
        # `os.rename` would silently replace it.
        src = touch(tmp_path / "a.cbz")
        dst = touch(tmp_path / "b.cbz")

        with pytest.raises(RenameConflictError, match="already exists"):
            _safe_rename(src, dst)

        assert src.is_file()

    def test_a_rename_onto_an_existing_symlink_is_refused(self, tmp_path: Path) -> None:
        src = touch(tmp_path / "a.cbz")
        dst = tmp_path / "b.cbz"
        dst.symlink_to(tmp_path / "nothing.cbz")

        with pytest.raises(RenameConflictError, match="already exists"):
            _safe_rename(src, dst)

    def test_a_vanished_source_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(RenameConflictError, match="vanished"):
            _safe_rename(tmp_path / "gone.cbz", tmp_path / "b.cbz")

    def test_an_ordinary_rename_goes_through(self, tmp_path: Path) -> None:
        src = touch(tmp_path / "a.cbz")
        dst = tmp_path / "b.cbz"

        _safe_rename(src, dst)

        assert dst.is_file()
        assert not src.exists()


class TestRecoveringAnInterruptedRun:
    """A killed run leaves a self-describing temp file; no journal is needed."""

    def test_a_dry_run_reports_the_leftover_and_changes_nothing(
        self, chrono_roots: tuple[Path, Path]
    ) -> None:
        dirs_root, _zips_root = chrono_roots
        leftover = touch(dirs_root / f"212 A Title{TEMP_SUFFIX}")

        recovered = recover_interrupted_renames(apply=False)

        assert recovered == [leftover]
        assert leftover.exists()
        assert not (dirs_root / "212 A Title").exists()

    def test_applying_completes_the_rename(self, chrono_roots: tuple[Path, Path]) -> None:
        dirs_root, _zips_root = chrono_roots
        leftover = touch(dirs_root / f"212 A Title{TEMP_SUFFIX}")

        recovered = recover_interrupted_renames(apply=True)

        assert recovered == [leftover]
        assert (dirs_root / "212 A Title").exists()
        assert not leftover.exists()

    def test_a_leftover_whose_destination_exists_is_refused_and_not_reported(
        self, chrono_roots: tuple[Path, Path]
    ) -> None:
        # Recovering would clobber a real artifact, so it is left for a human. It must
        # also not be returned, or the caller would believe it was dealt with.
        dirs_root, _zips_root = chrono_roots
        leftover = touch(dirs_root / f"212 A Title{TEMP_SUFFIX}")
        blocker = touch(dirs_root / "212 A Title")

        recovered = recover_interrupted_renames(apply=True)

        assert recovered == []
        assert leftover.exists()
        assert blocker.exists()

    def test_both_roots_are_swept(self, chrono_roots: tuple[Path, Path]) -> None:
        dirs_root, zips_root = chrono_roots
        touch(dirs_root / f"212 A Title{TEMP_SUFFIX}")
        touch(zips_root / f"212 A Title.cbz{TEMP_SUFFIX}")

        recovered = recover_interrupted_renames(apply=True)

        assert len(recovered) == BOTH_ROOTS
        assert (dirs_root / "212 A Title").exists()
        assert (zips_root / "212 A Title.cbz").exists()

    def test_an_ordinary_artifact_is_left_alone(self, chrono_roots: tuple[Path, Path]) -> None:
        dirs_root, _zips_root = chrono_roots
        ordinary = touch(dirs_root / "212 A Title")

        assert recover_interrupted_renames(apply=True) == []
        assert ordinary.exists()

    @pytest.mark.usefixtures("chrono_roots")
    def test_a_clean_tree_recovers_nothing(self) -> None:
        assert recover_interrupted_renames(apply=True) == []


class TestTheDryRunChangesNothing:
    def test_no_rename_happens_and_the_call_succeeds(self, tmp_path: Path) -> None:
        src = touch(tmp_path / "dirs" / "001 A Title")
        dst = tmp_path / "dirs" / "212 A Title"
        plan = RenamePlan(dest_dir_steps=[RenameStep(src, dst)])

        assert apply_rename_plan(plan, apply=False) == 0
        assert src.exists()
        assert not dst.exists()

    def test_no_symlink_is_recreated(self, tmp_path: Path) -> None:
        zip_file = touch(tmp_path / "zips" / "212 A Title.cbz")
        symlink = tmp_path / "series" / "Donald Duck" / "212 A Title.cbz"
        plan = RenamePlan(symlink_fixes=[SymlinkFix("A Title", zip_file, symlink.parent, symlink)])

        assert apply_rename_plan(plan, apply=False) == 0
        assert not symlink.exists()


class TestApplyingThePlan:
    def test_the_stages_run_dest_dirs_then_zips_then_symlinks(self, tmp_path: Path) -> None:
        # The order is mandatory: a symlink created before its zip is renamed would point
        # at the old name, so this asserts the link lands on the *final* zip.
        dest_dir = tmp_path / "dirs" / "001 A Title"
        dest_dir.mkdir(parents=True)
        old_zip = touch(tmp_path / "zips" / "001 A Title.cbz")
        new_zip = tmp_path / "zips" / "212 A Title.cbz"
        symlink = tmp_path / "series" / "Donald Duck" / "212 A Title.cbz"

        plan = RenamePlan(
            dest_dir_steps=[RenameStep(dest_dir, tmp_path / "dirs" / "212 A Title")],
            zip_steps=[RenameStep(old_zip, new_zip)],
            symlink_fixes=[SymlinkFix("A Title", new_zip, symlink.parent, symlink)],
        )

        assert apply_rename_plan(plan, apply=True) == 0
        assert (tmp_path / "dirs" / "212 A Title").is_dir()
        assert new_zip.is_file()
        assert symlink.resolve() == new_zip.resolve()

    def test_stale_symlinks_are_dropped(self, tmp_path: Path) -> None:
        zip_file = touch(tmp_path / "zips" / "212 A Title.cbz")
        symlink = tmp_path / "series" / "Donald Duck" / "212 A Title.cbz"
        stale = tmp_path / "series" / "Donald Duck" / "001 A Title.cbz"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.symlink_to(zip_file)

        plan = RenamePlan(
            symlink_fixes=[SymlinkFix("A Title", zip_file, symlink.parent, symlink, stale=(stale,))]
        )

        assert apply_rename_plan(plan, apply=True) == 0
        assert symlink.is_symlink()
        assert not stale.is_symlink()

    def test_an_empty_plan_is_a_no_op(self) -> None:
        assert apply_rename_plan(RenamePlan(), apply=True) == 0

    def test_a_failing_stage_reports_and_stops(self, tmp_path: Path) -> None:
        # The destination already exists, so the guard fires. Re-running is the documented
        # way to complete the rest.
        src = touch(tmp_path / "zips" / "001 A Title.cbz")
        blocked = touch(tmp_path / "zips" / "212 A Title.cbz")
        plan = RenamePlan(zip_steps=[RenameStep(src, blocked)])

        assert apply_rename_plan(plan, apply=True) == 1
        assert src.is_file()


class TestAPlanWithConflicts:
    def test_conflicts_abort_before_any_io(self, tmp_path: Path) -> None:
        src = touch(tmp_path / "dirs" / "001 A Title")
        dst = tmp_path / "dirs" / "212 A Title"
        conflict = ArtifactFix(
            kind=ArtifactKind.SERIES_SYMLINK,
            disposition=Disposition.CONFLICT,
            key="A Title",
            current=None,
            expected=dst,
            note='also claimed by "Another Title"',
        )
        plan = RenamePlan(dest_dir_steps=[RenameStep(src, dst)], conflicts=[conflict])

        assert apply_rename_plan(plan, apply=True) == 1
        assert src.exists()
        assert not dst.exists()

    def test_a_conflicting_plan_is_refused_on_a_dry_run_too(self, tmp_path: Path) -> None:
        # Otherwise the dry run would advertise renames that applying would never do.
        conflict = ArtifactFix(
            kind=ArtifactKind.ZIP,
            disposition=Disposition.CONFLICT,
            key="A Title",
            current=None,
            expected=tmp_path / "zips" / "212 A Title.cbz",
        )

        assert apply_rename_plan(RenamePlan(conflicts=[conflict]), apply=False) == 1


class TestDistinctExpectedPaths:
    """Two titles must not claim one path - symlinks are written unlink-then-link."""

    def test_two_titles_sharing_a_path_conflict(self, tmp_path: Path) -> None:
        shared = expected_for("A Title", tmp_path, 212)
        clash = ExpectedArtifacts(
            story_title="Another Title",
            key="Another Title",
            dest_dir=tmp_path / "dirs" / "213 Another Title",
            zip_file=tmp_path / "zips" / "213 Another Title.cbz",
            # The same series symlink: `number_in_series` collided.
            series_symlink=shared.series_symlink,
            year_symlink=tmp_path / "years" / "1949" / "213 Another Title.cbz",
        )

        conflicts = _check_expected_paths_are_distinct({"A Title": shared, "Another Title": clash})

        assert len(conflicts) == 1
        assert conflicts[0].kind is ArtifactKind.SERIES_SYMLINK
        assert "A Title" in conflicts[0].note

    def test_distinct_titles_do_not_conflict(self, tmp_path: Path) -> None:
        expected = {
            "A Title": expected_for("A Title", tmp_path, 212),
            "Another Title": expected_for("Another Title", tmp_path, 213),
        }

        assert _check_expected_paths_are_distinct(expected) == []


class TestClassifyingRenames:
    def test_an_artifact_under_another_number_is_a_rename(self, tmp_path: Path) -> None:
        root = tmp_path / "dirs"
        have = touch(root / "001 A Title")
        want = root / "212 A Title"
        fixes: list[ArtifactFix] = []

        steps = _plan_renames(
            ArtifactKind.DEST_DIR, {"A Title": want}, {"A Title": have}, root, fixes
        )

        assert [f.disposition for f in fixes] == [Disposition.RENAME]
        assert steps == [RenameStep(have, want)]

    def test_an_artifact_already_in_place_needs_no_step(self, tmp_path: Path) -> None:
        root = tmp_path / "dirs"
        want = touch(root / "212 A Title")
        fixes: list[ArtifactFix] = []

        steps = _plan_renames(
            ArtifactKind.DEST_DIR, {"A Title": want}, {"A Title": want}, root, fixes
        )

        assert [f.disposition for f in fixes] == [Disposition.OK]
        assert steps == []

    def test_an_expected_artifact_that_is_absent_is_missing(self, tmp_path: Path) -> None:
        root = tmp_path / "dirs"
        root.mkdir(parents=True)
        fixes: list[ArtifactFix] = []

        _plan_renames(ArtifactKind.DEST_DIR, {"A Title": root / "212 A Title"}, {}, root, fixes)

        assert [f.disposition for f in fixes] == [Disposition.MISSING]

    def test_an_artifact_no_title_claims_is_an_orphan(self, tmp_path: Path) -> None:
        # Left alone rather than deleted: it may be a title that was un-configured.
        root = tmp_path / "dirs"
        stray = touch(root / "999 Who Knows")
        fixes: list[ArtifactFix] = []

        steps = _plan_renames(ArtifactKind.DEST_DIR, {}, {"Who Knows": stray}, root, fixes)

        assert [f.disposition for f in fixes] == [Disposition.ORPHAN]
        assert steps == []


class TestClassifyingSymlinks:
    def test_a_symlink_is_missing_when_its_zip_is_not_built(self, tmp_path: Path) -> None:
        # Not RELINK: there is nothing to link to, and proposing one would produce a
        # dangling link that looks like a built comic.
        expected = {"A Title": expected_for("A Title", tmp_path, 212)}
        fixes: list[ArtifactFix] = []

        symlink_fixes = _plan_symlinks(expected, ActualArtifacts(), fixes)

        assert symlink_fixes == []
        assert {f.disposition for f in fixes} == {Disposition.MISSING}

    def test_a_symlink_is_planned_for_every_built_zip(self, tmp_path: Path) -> None:
        artifacts = expected_for("A Title", tmp_path, 212)
        actual = ActualArtifacts(zips={"A Title": artifacts.zip_file})
        fixes: list[ArtifactFix] = []

        symlink_fixes = _plan_symlinks({"A Title": artifacts}, actual, fixes)

        assert {fix.symlink for fix in symlink_fixes} == {
            artifacts.series_symlink,
            artifacts.year_symlink,
        }


class TestThePlanTally:
    def test_each_kind_is_tallied_separately(self) -> None:
        plan = RenamePlan(
            fixes=[
                ArtifactFix(ArtifactKind.ZIP, Disposition.RENAME, "a", None, None),
                ArtifactFix(ArtifactKind.ZIP, Disposition.RENAME, "b", None, None),
                ArtifactFix(ArtifactKind.ZIP, Disposition.OK, "c", None, None),
                ArtifactFix(ArtifactKind.DEST_DIR, Disposition.OK, "a", None, None),
            ]
        )

        assert plan.counts(ArtifactKind.ZIP) == {Disposition.RENAME: 2, Disposition.OK: 1}
        assert plan.counts(ArtifactKind.DEST_DIR) == {Disposition.OK: 1}

    def test_a_kind_with_nothing_found_tallies_empty(self) -> None:
        # `print_rename_plan` reports "nothing found" off this.
        assert RenamePlan().counts(ArtifactKind.YEAR_SYMLINK) == {}
