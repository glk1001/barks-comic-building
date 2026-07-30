# ruff: noqa: T201
"""Repair stale built-comic artifact names by renaming them, not rebuilding.

When titles are inserted into the chronology, every later title's chronological
number shifts and its already-built artifacts keep the old number. The integrity
checker then reports each such title twice - once as an unexpected file at the old
name, once as a missing/unbuilt comic at the new one. Rebuilding is very expensive;
renaming is nearly free, and nothing reads the old number back out of an artifact.

There is no single "offset" to apply. Inserting titles at several points in the
chronology shifts later titles by different amounts, and a title can also be
repositioned outright. Worse, series symlinks are numbered by `number_in_series`,
a counter that moves independently of the chronological one. So the repair is driven
entirely by matching on the *number-stripped* artifact name, which is unique across
every title.

Deletion invariant
------------------
This module performs only `os.rename`, `os.symlink`, and `os.unlink` **on symlinks**.
It never unlinks a regular file, never removes a directory, and never rewrites file
contents. A stale symlink is unlinked only once its replacement has been created.
"""

from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from barks_fantagraphics.comics_consts import (
    THE_CHRONOLOGICAL_DIR,
    THE_CHRONOLOGICAL_DIRS_DIR,
    THE_COMICS_DIR,
    THE_YEARS_COMICS_DIR,
)
from barks_fantagraphics.comics_utils import get_relpath
from loguru import logger

from barks_comic_building.build.zipping import create_symlink_zip

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from collections.abc import Set as AbstractSet

    from barks_fantagraphics.comics_database import ComicsDatabase

ERROR_MSG_PREFIX = "ERROR: "

# Artifact names are "NNN <title>" or "NNN <title> [<ISSUE>].cbz".
_CHRONO_PREFIX_RE = re.compile(r"^\d{3} ")

# Temp names encode their own destination and sit in the destination's directory, so
# an interrupted run leaves a self-describing leftover that `check_files_in_dir` will
# report as unexpected on the very next check.
TEMP_SUFFIX = ".barks-fix-tmp"

CBZ_SUFFIX = ".cbz"


class RenameConflictError(Exception):
    """Raised when a set of renames cannot be ordered safely."""


class ArtifactKind(StrEnum):
    """The four kinds of built artifact whose name carries a number."""

    DEST_DIR = "dest dir"
    ZIP = "zip"
    SERIES_SYMLINK = "series symlink"
    YEAR_SYMLINK = "year symlink"


class Disposition(StrEnum):
    """What the fix intends to do with one artifact."""

    OK = "ok"  # already at its expected path
    RENAME = "rename"  # stale artifact found under another number
    RELINK = "relink"  # symlink: recreate against the final zip name
    MISSING = "missing"  # nothing on disk - needs a real build
    ORPHAN = "orphan"  # on disk, claimed by no configured title
    CONFLICT = "conflict"  # cannot be repaired safely - abort before any I/O


@dataclass(frozen=True)
class ExpectedArtifacts:
    """Where a configured title's four artifacts should live right now."""

    story_title: str
    key: str
    dest_dir: Path
    zip_file: Path
    series_symlink: Path
    year_symlink: Path


@dataclass(frozen=True)
class ArtifactFix:
    """One artifact's classification, for the report."""

    kind: ArtifactKind
    disposition: Disposition
    key: str | None
    current: Path | None
    expected: Path | None
    note: str = ""


@dataclass(frozen=True)
class RenameStep:
    """A single rename. `is_temp` marks the two halves of a cycle break."""

    src: Path
    dst: Path
    is_temp: bool = False


@dataclass(frozen=True)
class SymlinkFix:
    """Recreate one symlink against the final zip name, dropping stale copies."""

    key: str
    zip_file: Path
    symlink_dir: Path
    symlink: Path
    stale: tuple[Path, ...] = ()


@dataclass
class ActualArtifacts:
    """What is actually on disk, indexed by match key."""

    dest_dirs: dict[str, Path] = field(default_factory=dict)
    zips: dict[str, Path] = field(default_factory=dict)
    series_symlinks: dict[str, list[Path]] = field(default_factory=dict)
    year_symlinks: dict[str, list[Path]] = field(default_factory=dict)
    unparsable: list[tuple[ArtifactKind, Path]] = field(default_factory=list)


@dataclass
class RenamePlan:
    """Everything the fix intends to do, derived fresh from disk on every run."""

    dest_dir_steps: list[RenameStep] = field(default_factory=list)
    zip_steps: list[RenameStep] = field(default_factory=list)
    symlink_fixes: list[SymlinkFix] = field(default_factory=list)
    fixes: list[ArtifactFix] = field(default_factory=list)
    conflicts: list[ArtifactFix] = field(default_factory=list)
    unbuilt_titles: list[str] = field(default_factory=list)
    load_errors: list[str] = field(default_factory=list)
    # Carried through from the disk scan so the report can name them: an artifact whose
    # name does not parse is matched to no title, so it is renamed by nothing and
    # reported by nothing else either.
    unparsable: list[tuple[ArtifactKind, Path]] = field(default_factory=list)

    def counts(self, kind: ArtifactKind) -> dict[Disposition, int]:
        """Return the per-disposition tally for one artifact kind."""
        tally: dict[Disposition, int] = {}
        for fix in self.fixes:
            if fix.kind == kind:
                tally[fix.disposition] = tally.get(fix.disposition, 0) + 1
        return tally


def _strip_chrono_prefix(name: str) -> str | None:
    """Strip a leading "NNN " from an artifact name, or return None if absent."""
    if not _CHRONO_PREFIX_RE.match(name):
        return None
    return _CHRONO_PREFIX_RE.sub("", name, count=1)


def dest_dir_key(dir_name: str) -> str | None:
    """Return the match key for a dest dir name ("212 Foo Bar" -> "Foo Bar")."""
    return _strip_chrono_prefix(dir_name)


def zip_key(file_name: str) -> str | None:
    """Return the match key for a comic zip name.

    "212 Foo Bar [WDCS 31].cbz" -> "Foo Bar".

    The issue suffix is deliberately discarded. The dest dir name carries no issue,
    so the bare title is the only key that works uniformly across all four artifact
    kinds - and it also survives an issue re-attribution, which would otherwise
    silently downgrade a title to orphan-plus-missing and propose a needless rebuild.
    """
    stem = _strip_chrono_prefix(Path(file_name).stem)
    if stem is None:
        return None
    return stem.rsplit(" [", 1)[0]


def build_expected_artifacts(
    comics_db: ComicsDatabase,
) -> tuple[dict[str, ExpectedArtifacts], list[str]]:
    """Return the expected artifacts for every configured title, plus load errors.

    Iterates the configured story titles - the same set `check_no_unexpected_files`
    uses - so an unconfigured chronological entry is never reported as missing.

    Args:
        comics_db: The comics database.

    Returns:
        A (key -> ExpectedArtifacts) mapping and a list of per-title load errors.

    """
    expected: dict[str, ExpectedArtifacts] = {}
    load_errors: list[str] = []

    for story_title in comics_db.get_all_story_titles():
        try:
            comic = comics_db.get_comic_book(story_title)
        except (OSError, RuntimeError, KeyError, AssertionError) as exc:
            # One malformed ini must not abort a whole-tree repair.
            load_errors.append(f'"{story_title}": {exc}')
            continue

        # Derive the key from the dest dir name so both sides of the match go through
        # the same title normalisation.
        key = dest_dir_key(comic.get_dest_rel_dirname())
        if key is None:
            load_errors.append(
                f'"{story_title}": unexpected dest dir name "{comic.get_dest_rel_dirname()}".'
            )
            continue

        expected[key] = ExpectedArtifacts(
            story_title=story_title,
            key=key,
            dest_dir=comic.get_dest_dir(),
            zip_file=comic.get_dest_comic_zip(),
            series_symlink=comic.get_dest_series_comic_zip_symlink(),
            year_symlink=comic.get_dest_year_comic_zip_symlink(),
        )

    return expected, load_errors


def _iter_visible(dir_path: Path) -> list[Path]:
    """Return a directory's entries, sorted, skipping dotfiles."""
    if not dir_path.is_dir():
        return []
    return sorted(p for p in dir_path.iterdir() if not p.name.startswith("."))


def _scan_symlink_namespace(
    root_dirs: Iterable[Path],
    kind: ArtifactKind,
    actual: ActualArtifacts,
    index: dict[str, list[Path]],
) -> None:
    """Index every ``NNN <title> [<ISSUE>].cbz`` symlink under ``root_dirs``."""
    for root in root_dirs:
        for entry in _iter_visible(root):
            if entry.suffix != CBZ_SUFFIX:
                continue
            key = zip_key(entry.name)
            if key is None:
                actual.unparsable.append((kind, entry))
                continue
            index.setdefault(key, []).append(entry)


def scan_actual_artifacts() -> ActualArtifacts:
    """Scan the four artifact namespaces on disk and index them by match key.

    The symlink namespaces are scanned wider than the expected set - every series
    directory and every year directory - because a title that changed series or
    submitted year leaves its stale symlink in a *different* directory. Scanning
    only the expected parent would miss it and leave a mystery orphan.

    Returns:
        Everything found on disk, keyed for matching.

    """
    actual = ActualArtifacts()

    for entry in _iter_visible(THE_CHRONOLOGICAL_DIRS_DIR):
        key = dest_dir_key(entry.name)
        if key is None:
            actual.unparsable.append((ArtifactKind.DEST_DIR, entry))
        else:
            actual.dest_dirs[key] = entry

    for entry in _iter_visible(THE_CHRONOLOGICAL_DIR):
        if entry.suffix != CBZ_SUFFIX:
            actual.unparsable.append((ArtifactKind.ZIP, entry))
            continue
        key = zip_key(entry.name)
        if key is None:
            actual.unparsable.append((ArtifactKind.ZIP, entry))
        else:
            actual.zips[key] = entry

    known_subdirs = {THE_CHRONOLOGICAL_DIRS_DIR, THE_CHRONOLOGICAL_DIR, THE_YEARS_COMICS_DIR}
    series_dirs = [
        d for d in _iter_visible(THE_COMICS_DIR) if d.is_dir() and d not in known_subdirs
    ]
    _scan_symlink_namespace(
        series_dirs, ArtifactKind.SERIES_SYMLINK, actual, actual.series_symlinks
    )

    year_dirs = [d for d in _iter_visible(THE_YEARS_COMICS_DIR) if d.is_dir()]
    _scan_symlink_namespace(year_dirs, ArtifactKind.YEAR_SYMLINK, actual, actual.year_symlinks)

    return actual


def temp_path_for(dst: Path) -> Path:
    """Return the temp path used to break a rename cycle ending at ``dst``.

    It sits in the destination's own directory (so the rename is atomic) and encodes
    its final destination in its name (so an interrupted run needs no journal to
    recover from - the leftover says where it was going).
    """
    return dst.with_name(dst.name + TEMP_SUFFIX)


def order_moves(moves: Mapping[Path, Path], occupied: AbstractSet[Path]) -> list[RenameStep]:
    """Order a set of renames so no rename ever clobbers a live path.

    ``moves`` is injective with distinct sources, so every component of the move
    graph is a simple path or a simple cycle. Paths unroll from whichever end is
    already free; each cycle is broken with exactly one temp rename.

    Pure - does no I/O. Deterministic, so a dry run and the subsequent apply print
    identically.

    Args:
        moves: The renames to order, as source -> destination.
        occupied: Every path that currently exists in the namespace, including
            entries that are not being moved.

    Returns:
        The renames in a safe order.

    Raises:
        RenameConflictError: If two moves share a destination, a destination is held
            by something that is not itself a source, or a move crosses directories.

    """
    destinations = list(moves.values())
    if len(set(destinations)) != len(destinations):
        msg = "Two renames share a destination."
        raise RenameConflictError(msg)

    for src, dst in moves.items():
        if dst in occupied and dst not in moves:
            msg = f'Destination "{dst}" is held by something that is not being moved.'
            raise RenameConflictError(msg)
        if src.parent != dst.parent:
            msg = f'Cross-directory move: "{src}" -> "{dst}".'
            raise RenameConflictError(msg)

    steps: list[RenameStep] = []
    remaining = dict(moves)

    # In-degree is at most 1, so at most one source ever waits on a given path.
    blocked_on = {dst: src for src, dst in moves.items() if dst in occupied}

    ready = deque(sorted(src for src, dst in remaining.items() if dst not in occupied))
    while ready:
        src = ready.popleft()
        if src not in remaining:
            continue
        steps.append(RenameStep(src, remaining.pop(src)))
        waiter = blocked_on.get(src)
        if waiter is not None and waiter in remaining:
            ready.append(waiter)

    # Anything left lies on a cycle. Break each with one temp, then unroll backwards.
    while remaining:
        start = min(remaining)
        start_dst = remaining.pop(start)
        tmp = temp_path_for(start_dst)

        steps.append(RenameStep(start, tmp, is_temp=True))
        node = start
        while (waiter := blocked_on.get(node)) is not None and waiter in remaining:
            steps.append(RenameStep(waiter, remaining.pop(waiter)))
            node = waiter
        steps.append(RenameStep(tmp, start_dst, is_temp=True))

    return steps


def _check_expected_paths_are_distinct(
    expected: Mapping[str, ExpectedArtifacts],
) -> list[ArtifactFix]:
    """Return a conflict for every expected path claimed by more than one title.

    Uniqueness of the chronological names follows from the database's own duplicate
    guard, but the *series* symlink name uses `number_in_series`, and symlinks are
    written unlink-then-link. Two titles in one series sharing that number would
    therefore silently overwrite each other, leaving one title with no symlink at
    all. Cheap to rule out, and the one place "just recreate everything" is not
    self-evidently safe.
    """
    seen: dict[Path, str] = {}
    conflicts: list[ArtifactFix] = []

    for artifacts in expected.values():
        for kind, path in (
            (ArtifactKind.DEST_DIR, artifacts.dest_dir),
            (ArtifactKind.ZIP, artifacts.zip_file),
            (ArtifactKind.SERIES_SYMLINK, artifacts.series_symlink),
            (ArtifactKind.YEAR_SYMLINK, artifacts.year_symlink),
        ):
            if path in seen:
                conflicts.append(
                    ArtifactFix(
                        kind=kind,
                        disposition=Disposition.CONFLICT,
                        key=artifacts.key,
                        current=None,
                        expected=path,
                        note=f'also claimed by "{seen[path]}"',
                    ),
                )
            else:
                seen[path] = artifacts.story_title

    return conflicts


def _plan_renames(
    kind: ArtifactKind,
    expected_paths: Mapping[str, Path],
    actual_paths: Mapping[str, Path],
    namespace_root: Path,
    fixes: list[ArtifactFix],
) -> list[RenameStep]:
    """Classify one artifact kind and return its ordered rename steps."""
    moves: dict[Path, Path] = {}

    for key, want in sorted(expected_paths.items()):
        have = actual_paths.get(key)
        if have is None:
            fixes.append(ArtifactFix(kind, Disposition.MISSING, key, None, want))
        elif have == want:
            fixes.append(ArtifactFix(kind, Disposition.OK, key, have, want))
        else:
            fixes.append(ArtifactFix(kind, Disposition.RENAME, key, have, want))
            moves[have] = want

    fixes.extend(
        ArtifactFix(kind, Disposition.ORPHAN, key, actual_paths[key], None)
        for key in sorted(set(actual_paths) - set(expected_paths))
    )

    occupied = set(_iter_visible(namespace_root))
    return order_moves(moves, occupied)


def _plan_symlinks(
    expected: Mapping[str, ExpectedArtifacts],
    actual: ActualArtifacts,
    fixes: list[ArtifactFix],
) -> list[SymlinkFix]:
    """Plan symlink recreation for every title whose zip will exist.

    Symlinks are recreated unconditionally rather than renamed. They are relative,
    so renaming one preserves a now-wrong target; and `number_in_series` shifts
    independently of the chronological number, so "which symlinks changed" needs
    case analysis that recreating everything makes unnecessary. ~900 symlinks costs
    microseconds.
    """
    symlink_fixes: list[SymlinkFix] = []

    for key, artifacts in sorted(expected.items()):
        zip_exists = key in actual.zips
        for kind, want, found in (
            (ArtifactKind.SERIES_SYMLINK, artifacts.series_symlink, actual.series_symlinks),
            (ArtifactKind.YEAR_SYMLINK, artifacts.year_symlink, actual.year_symlinks),
        ):
            current = found.get(key, [])
            if not zip_exists:
                fixes.append(ArtifactFix(kind, Disposition.MISSING, key, None, want))
                continue

            fixes.append(
                ArtifactFix(kind, Disposition.RELINK, key, current[0] if current else None, want),
            )
            symlink_fixes.append(
                SymlinkFix(
                    key=key,
                    zip_file=artifacts.zip_file,
                    symlink_dir=want.parent,
                    symlink=want,
                    stale=tuple(sorted(p for p in current if p != want)),
                ),
            )

    for kind, found in (
        (ArtifactKind.SERIES_SYMLINK, actual.series_symlinks),
        (ArtifactKind.YEAR_SYMLINK, actual.year_symlinks),
    ):
        for key in sorted(set(found) - set(expected)):
            fixes.extend(
                ArtifactFix(kind, Disposition.ORPHAN, key, path, None) for path in found[key]
            )

    return symlink_fixes


def build_rename_plan(comics_db: ComicsDatabase) -> RenamePlan:
    """Work out how to move every stale built artifact onto its current name.

    Derived fresh from disk on every call, which is what makes the fix idempotent:
    an artifact already at its expected path classifies as OK and produces no step,
    so re-running after an interruption simply completes the remainder.

    Args:
        comics_db: The comics database.

    Returns:
        The full plan, including classifications, conflicts, and unbuilt titles.

    """
    expected, load_errors = build_expected_artifacts(comics_db)
    plan = RenamePlan(load_errors=load_errors)

    plan.conflicts = _check_expected_paths_are_distinct(expected)
    if plan.conflicts:
        return plan

    actual = scan_actual_artifacts()
    plan.unparsable = actual.unparsable

    try:
        plan.dest_dir_steps = _plan_renames(
            ArtifactKind.DEST_DIR,
            {k: e.dest_dir for k, e in expected.items()},
            actual.dest_dirs,
            THE_CHRONOLOGICAL_DIRS_DIR,
            plan.fixes,
        )
        plan.zip_steps = _plan_renames(
            ArtifactKind.ZIP,
            {k: e.zip_file for k, e in expected.items()},
            actual.zips,
            THE_CHRONOLOGICAL_DIR,
            plan.fixes,
        )
    except RenameConflictError as exc:
        plan.conflicts.append(
            ArtifactFix(ArtifactKind.ZIP, Disposition.CONFLICT, None, None, None, str(exc)),
        )
        return plan

    plan.symlink_fixes = _plan_symlinks(expected, actual, plan.fixes)

    # A title with no dest dir and no zip has never been built - a rename cannot help.
    plan.unbuilt_titles = sorted(
        artifacts.story_title
        for key, artifacts in expected.items()
        if key not in actual.dest_dirs and key not in actual.zips
    )

    return plan


def _safe_rename(src: Path, dst: Path) -> None:
    """Rename ``src`` to ``dst``, refusing to clobber anything.

    `os.rename` silently replaces an existing regular file on POSIX, and a single
    modelling error here would destroy a comic zip that costs a full rebuild to
    recreate. The destination guard is what makes that impossible.

    Raises:
        RenameConflictError: If the source has vanished or the destination exists.

    """
    if not (src.exists() or src.is_symlink()):
        msg = f'Rename source has vanished: "{src}".'
        raise RenameConflictError(msg)
    if dst.exists() or dst.is_symlink():
        msg = f'Rename destination already exists: "{dst}".'
        raise RenameConflictError(msg)

    os.rename(src, dst)  # noqa: PTH104


def recover_interrupted_renames(*, apply: bool) -> list[Path]:
    """Complete any rename left half-done by an interrupted run.

    A leftover is named "<destination><TEMP_SUFFIX>", so recovery needs no journal.
    This runs *before* the plan is built: otherwise the leftover would look like an
    orphan and the real artifact like a missing one, which reads as a false
    "needs rebuild".

    Args:
        apply: Whether to actually perform the recovery renames.

    Returns:
        The temp paths that were (or would be) recovered.

    """
    recovered: list[Path] = []

    for root in (THE_CHRONOLOGICAL_DIRS_DIR, THE_CHRONOLOGICAL_DIR):
        for entry in _iter_visible(root):
            if not entry.name.endswith(TEMP_SUFFIX):
                continue

            final = entry.with_name(entry.name[: -len(TEMP_SUFFIX)])
            if final.exists() or final.is_symlink():
                print(
                    f"{ERROR_MSG_PREFIX}Cannot recover interrupted rename"
                    f' "{get_relpath(entry)}": "{get_relpath(final)}" already exists.',
                )
                continue

            recovered.append(entry)
            print(f'Recovering interrupted rename: "{entry.name}" -> "{final.name}".')
            if apply:
                _safe_rename(entry, final)

    return recovered


def _print_rename_steps(title: str, steps: list[RenameStep]) -> None:
    """Print one class of renames as names only - the parent dir is constant."""
    if not steps:
        return

    num_temp = sum(1 for s in steps if s.is_temp)
    temp_note = f", {num_temp} via temp" if num_temp else ""
    print(f"\n{title} ({len(steps)}{temp_note}):")
    for step in steps:
        print(f'  "{step.src.name}"  ->  "{step.dst.name}"')


def print_rename_plan(plan: RenamePlan) -> None:
    """Print the whole plan: summary table, renames, and everything left alone."""
    print("\nArtifact rename plan")
    for kind in ArtifactKind:
        tally = plan.counts(kind)
        parts = [f"{tally[d]} {d}" for d in Disposition if tally.get(d)]
        print(f"  {kind:<16} {'   '.join(parts) if parts else 'nothing found'}")

    _print_rename_steps("Dest dir renames", plan.dest_dir_steps)
    _print_rename_steps("Zip renames", plan.zip_steps)

    num_stale = sum(len(f.stale) for f in plan.symlink_fixes)
    stale_note = f", dropping {num_stale} stale" if num_stale else ""
    print(f"\nSymlinks to recreate: {len(plan.symlink_fixes)}{stale_note}.")

    orphans = [f for f in plan.fixes if f.disposition == Disposition.ORPHAN]
    print(f"\nOrphans - on disk but claimed by no configured title ({len(orphans)}). Left alone.")
    for fix in orphans:
        print(f'  [{fix.kind}] "{fix.current}"')

    if plan.unbuilt_titles:
        print(
            f"\nNot built - these need a real build, not a rename ({len(plan.unbuilt_titles)}):",
        )
        for story_title in plan.unbuilt_titles:
            print(f'  uv run barks-build --title "{story_title}"')

    if plan.unparsable:
        print(
            f"\nUnparsable names - matched to no title, so renamed by nothing"
            f" ({len(plan.unparsable)}). Left alone:",
        )
        for kind, path in plan.unparsable:
            print(f'  [{kind}] "{path.name}"')

    if plan.load_errors:
        print(f"\nTitles that could not be loaded ({len(plan.load_errors)}):")
        for err in plan.load_errors:
            print(f"  {err}")


def apply_rename_plan(plan: RenamePlan, *, apply: bool) -> int:
    """Execute the plan, or with ``apply=False`` just report it.

    Stage order is mandatory - dest dirs, then zips, then symlinks - so symlinks are
    always created against the final zip names. A failure in any stage aborts before
    the next: half-renamed zips must never get symlinks pointing into a mixture.
    Re-running completes the remainder.

    Args:
        plan: The plan to execute.
        apply: Whether to actually change anything.

    Returns:
        0 on success, 1 if the plan has conflicts or a stage failed.

    """
    if plan.conflicts:
        print(f"\n{ERROR_MSG_PREFIX}Cannot fix artifact names - conflicting expected paths:")
        for fix in plan.conflicts:
            print(f'  [{fix.kind}] "{fix.expected or fix.current or ""}" {fix.note}')
        print("\nNothing was changed.")
        return 1

    print_rename_plan(plan)

    num_renames = len(plan.dest_dir_steps) + len(plan.zip_steps)
    if not apply:
        print("\nDRY RUN - nothing was changed.")
        print(
            f"Re-run with --fix-names --apply to perform {num_renames} renames"
            f" and {len(plan.symlink_fixes)} symlink recreations.",
        )
        return 0

    if not num_renames and not plan.symlink_fixes:
        print("\nNothing to do.")
        return 0

    print(f"\nApplying {num_renames} renames...")
    try:
        _execute_plan(plan)
    except (RenameConflictError, OSError) as exc:
        print(f"\n{ERROR_MSG_PREFIX}{exc}")
        print("Aborted part-way. Re-run to complete the remaining work.")
        return 1

    print("\nDone.")
    return 0


def _execute_plan(plan: RenamePlan) -> None:
    """Perform the plan's renames and symlink recreations, in the mandatory order."""
    for step in plan.dest_dir_steps:
        logger.info(f'Renaming dest dir "{step.src.name}" -> "{step.dst.name}".')
        _safe_rename(step.src, step.dst)

    for step in plan.zip_steps:
        logger.info(f'Renaming zip "{step.src.name}" -> "{step.dst.name}".')
        _safe_rename(step.src, step.dst)

    print(f"Recreating {len(plan.symlink_fixes)} symlinks...")
    for fix in plan.symlink_fixes:
        create_symlink_zip(fix.zip_file, fix.symlink_dir, fix.symlink)
        for stale in fix.stale:
            if stale.is_symlink():
                logger.info(f'Removing stale symlink "{get_relpath(stale)}".')
                stale.unlink()


def run_artifact_rename_fix(comics_db: ComicsDatabase, *, apply: bool) -> int:
    """Recover, plan, report and optionally execute the artifact rename fix.

    Args:
        comics_db: The comics database.
        apply: Whether to actually change anything.

    Returns:
        0 on success, 1 otherwise.

    """
    if not apply:
        print(
            "\nNOTE: close the Barks Reader before applying - it opens comics by their"
            "\n      current name. Backups still hold the old names, so the next"
            "\n      'rsync --delete' will re-transfer every renamed comic.",
        )

    recover_interrupted_renames(apply=apply)

    return apply_rename_plan(build_rename_plan(comics_db), apply=apply)
