"""Staleness verdicts for the build integrity checks.

The question these answer is always the same: was this artifact built before one of the
things it was built *from*? Two rules keep the answers consistent.

**Existence and staleness are separate findings.** A missing zip is reported missing and
nothing else - there is no timestamp to compare it against, and also flagging it out of
date would double-count one fault. This module used to disagree with its caller on
exactly that point: it called a missing zip not-stale while the caller called it missing,
and one predicate would `stat()` a symlink that was not there and raise.

**These functions report nothing.** They return verdicts; the caller owns all output. A
predicate that logged its own finding at DEBUG while its caller printed the same finding
at ERROR - in different words - is how one fault came to be described two ways.
"""

from __future__ import annotations

import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from barks_fantagraphics import panel_bounding
from barks_fantagraphics.comics_utils import (
    get_abbrev_path,
    get_timestamp,
    get_timestamp_as_str,
    get_timestamp_str,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from barks_fantagraphics.pages import SrceDependency

DATE_SEP = "-"
DATE_TIME_SEP = " "
HOUR_SEP = ":"

# One tuple, so no call site can format a timestamp without separators. One of the eleven
# used to, and rendered its timestamp in a different format from the other ten.
TIMESTAMP_SEPS = (DATE_SEP, DATE_TIME_SEP, HOUR_SEP)


def links_to(link: Path, source: Path) -> bool:
    """Return whether ``link`` is already a symlink pointing at ``source``.

    Staging exists to let a restage be run freely, so it must be able to do nothing.
    That is not cosmetic here: `get_timestamp` reads a symlink's *own* mtime rather
    than its target's, deliberately, so that re-pointing a link marks everything built
    from it stale. Re-creating a link that already pointed at the right source sets
    that same clock forward without anything having changed, and the build then
    refuses a page whose segments file is in fact still current.

    The pages this bites are exactly the ones with a staged image but a
    collection-computed segments file - a one-pager whose source volume never
    segmented that page, because the one-pager belongs to no title. Their segments
    file is a real file that no restage touches, so only the link moves.

    Args:
        link: The staged path to test.
        source: The file the link should be pointing at.

    Returns:
        True if the link exists, is a symlink, and already resolves to ``source``.

    """
    if not link.is_symlink():
        return False

    return link.readlink() == source


@contextmanager
def quiet_panel_bbox_height_warnings() -> Iterator[None]:
    """Silence the shared panel-bounding height warning while a check resolves pages.

    A short page legitimately has a panels bbox shorter than the volume average, and a
    check that visits every page of every title would otherwise warn on all of them.

    Restored on the way out because this is a module global in a *shared* package. The
    unrestored assignment it replaces was harmless only for as long as nothing called
    this twice in one process - the moment a test does, the flag leaks into every later
    test in the session.
    """
    previous = panel_bounding.warn_on_panels_bbox_height_less_than_av
    panel_bounding.warn_on_panels_bbox_height_less_than_av = False
    try:
        yield
    finally:
        panel_bounding.warn_on_panels_bbox_height_less_than_av = previous


def dating_dependencies(
    dependencies: Sequence[SrceDependency], ini_file: Path
) -> list[SrceDependency]:
    """Drop the dependencies whose timestamps must not date a build.

    Only the ini file is dropped, and for two reasons that both point the same way.

    Its content is already checked properly: `check_hashes` compares the ini's hash
    against the `ini_hash` recorded in the comic's metadata at build time, so a real edit
    is caught exactly, with no reference to timestamps at all.

    And its timestamp is not evidence of anything. The ini files are git-tracked, in a
    different repository from the comics, so a checkout, pull or branch switch rewrites
    every mtime without changing a byte. Treating that as "the build is stale" reported
    2982 of 3323 findings on one real tree - 90% of the report - from a single bulk mtime
    bump in which not one ini's content had actually changed.

    The intro inset and a hand-drawn panel bounds fix stay. They are content files under
    the comics root rather than in git, nothing hashes them, and an edit to either really
    does mean the page needs rebuilding.

    Args:
        dependencies: A dest page's dependencies, as the pipeline reports them.
        ini_file: The comic's ini file.

    Returns:
        The dependencies that may date the build.

    """
    return [dependency for dependency in dependencies if dependency.file != ini_file]


@dataclass(frozen=True, slots=True)
class MaxTimestamp:
    """The newest file of a set, paired with its timestamp.

    Bundled rather than kept as two loose fields so a caller cannot report a staleness
    against a timestamp it is unable to name the file for. That pairing used to be
    maintained by hand across two fields assigned 380 lines apart, and guarded at the
    read end by a bare `assert`.
    """

    file: Path | zipfile.Path
    timestamp: float


@dataclass(frozen=True, slots=True)
class ZipOutOfDateErrors:
    """The verdict on a comic's zip file."""

    file: Path | None = None
    missing: bool = False
    out_of_date_wrt_srce: bool = False
    out_of_date_wrt_dest: bool = False
    timestamp: float = 0.0


@dataclass(frozen=True, slots=True)
class ZipSymlinkOutOfDateErrors:
    """The verdict on one of a comic's two zip symlinks."""

    symlink: Path | None = None
    missing: bool = False
    out_of_date_wrt_zip: bool = False
    out_of_date_wrt_dest: bool = False
    timestamp: float = 0.0


def fold_max(
    current: MaxTimestamp | None,
    file: Path | zipfile.Path,
    timestamp: float,
) -> MaxTimestamp | None:
    """Fold one file into a running maximum, returning the newer of the two.

    Args:
        current: The maximum so far, or None if nothing has been folded in yet.
        file: The candidate file.
        timestamp: The candidate's timestamp.

    Returns:
        Whichever of the two is newer.

    """
    if timestamp < 0:
        # `get_restored_srce_dependencies` uses -1 for a stage whose file is not on disk.
        # A file that is not there is a finding of its own, never the newest input.
        return current

    if current is not None and timestamp <= current.timestamp:
        return current

    return MaxTimestamp(file, timestamp)


def is_stale(timestamp: float, reference: MaxTimestamp | None) -> bool:
    """Return whether something of this timestamp predates `reference`.

    Pure arithmetic - the caller has already stat'ed once and passes the result, so no
    check here stats the same file twice.

    A None reference is not stale. A check that could not work out what its inputs were
    reports nothing rather than reporting everything, which is the failure to avoid in
    both directions: a dead check and a check that fires on everything are equally
    useless.

    Args:
        timestamp: The artifact's timestamp.
        reference: The newest input it was built from, or None if unknown.

    Returns:
        True if the artifact is older than its newest input.

    """
    if reference is None:
        return False

    return timestamp < reference.timestamp


@dataclass(frozen=True, slots=True)
class ChainStaleness:
    """The verdict on one dest page's restore chain."""

    # (the newer dependency, the older thing that was built from it)
    stale_pairs: list[tuple[Path, Path]]
    max_srce: MaxTimestamp | None


def walk_srce_dependency_chain(
    dependencies: Sequence[SrceDependency],
    dest_file: Path,
    dest_timestamp: float,
    max_srce: MaxTimestamp | None,
    *,
    is_a_comic: bool,
) -> ChainStaleness:
    """Walk a dest page's restore chain newest-first and report any inversion.

    `get_restored_srce_dependencies` returns the chain in pipeline order, latest stage
    first: panel segments, restored, restored-upscayled, restored-svg, upscayled,
    original. Each stage was produced *from* the next, so timestamps must decrease along
    the walk; a stage newer than the thing derived from it means that thing needs
    rebuilding. The dest page is the head of the chain.

    A timestamp of -1 is the sentinel for a stage whose file is not on disk, and is always
    an inversion - that is what the sign test is for. The reported pair names the missing
    file rather than a timestamp comparison, and it is reported exactly once: the stage
    after a missing one is not paired against it, because that pair's message can only name
    the same absent file again. The walk resumes comparing from that stage, so a real
    inversion further down the chain is still found.

    Independent dependencies - the ini file, the intro inset, a hand-drawn panel bounds
    fix - are not part of the chain, because nothing was derived from them. They only
    raise the maximum.

    Args:
        dependencies: The dest page's restore chain, latest stage first.
        dest_file: The dest page at the head of the chain.
        dest_timestamp: The dest page's timestamp.
        max_srce: The running newest-source maximum to fold into.
        is_a_comic: False for the non-comic titles, whose pages have no restore chain to
            be inconsistent - they still raise the maximum.

    Returns:
        The inversions found, and the updated maximum.

    """
    stale_pairs: list[tuple[Path, Path]] = []
    prev_timestamp = dest_timestamp
    prev_file = dest_file

    for dependency in dependencies:
        timestamp = dependency.timestamp

        if isinstance(dependency.file, zipfile.Path):
            # Only the intro inset can live inside a zip, and it is always independent, so
            # it never enters the chain. Fold it into the maximum and move on. Narrowing
            # here rather than at the reporting end is what keeps `stale_pairs` plain
            # `Path`s; it used to be asserted 380 lines away, and held only by luck.
            max_srce = fold_max(max_srce, dependency.file, timestamp)
            continue

        if not dependency.independent and is_a_comic:
            # A missing stage is its own finding, reported once. The `prev_timestamp >= 0`
            # guard is what keeps it to once: the sentinel is lower than every real
            # timestamp, so without it the next stage that *is* on disk compares newer than
            # -1 and gets paired against the absent file too - and the message for that pair
            # names the same missing file a second time, because naming it is all the pair
            # can say.
            if timestamp < 0 or (prev_timestamp >= 0 and timestamp > prev_timestamp):
                stale_pairs.append((dependency.file, prev_file))
            prev_timestamp = timestamp
            prev_file = dependency.file

        max_srce = fold_max(max_srce, dependency.file, timestamp)

    return ChainStaleness(stale_pairs, max_srce)


def check_zip_freshness(
    zip_file: Path,
    max_srce: MaxTimestamp | None,
    max_dest: MaxTimestamp | None,
) -> ZipOutOfDateErrors:
    """Grade a comic's zip against the sources and the dest pages it was built from.

    Args:
        zip_file: The comic's zip.
        max_srce: The newest source file the comic was built from, if known.
        max_dest: The newest dest page, if known.

    Returns:
        The verdict. A missing zip is reported missing and nothing else.

    """
    if not zip_file.is_file():
        return ZipOutOfDateErrors(file=zip_file, missing=True)

    timestamp = get_timestamp(zip_file)

    return ZipOutOfDateErrors(
        file=zip_file,
        timestamp=timestamp,
        out_of_date_wrt_srce=is_stale(timestamp, max_srce),
        out_of_date_wrt_dest=is_stale(timestamp, max_dest),
    )


def check_zip_symlink_freshness(
    symlink: Path,
    zip_errors: ZipOutOfDateErrors,
    max_dest: MaxTimestamp | None,
) -> ZipSymlinkOutOfDateErrors:
    """Grade one of a comic's zip symlinks against the zip and the dest pages.

    Each symlink is graded independently of the other. `check_zip_files` used to
    `return` at the first missing one, so a missing series symlink hid the year
    symlink's state entirely and two runs were needed to see both faults.

    `get_timestamp` uses lstat for a symlink, so a *dangling* link still grades rather
    than raising - it is the link's own age that matters here, not its target's.

    Args:
        symlink: The symlink to grade.
        zip_errors: The zip's verdict, which supplies the reference to compare against.
        max_dest: The newest dest page, if known.

    Returns:
        The verdict. A missing symlink is reported missing and nothing else.

    """
    if not symlink.is_symlink():
        return ZipSymlinkOutOfDateErrors(symlink=symlink, missing=True)

    timestamp = get_timestamp(symlink)

    # A missing zip is no reference to compare against - its absence is already reported.
    zip_reference = (
        None
        if zip_errors.missing or zip_errors.file is None
        else MaxTimestamp(zip_errors.file, zip_errors.timestamp)
    )

    return ZipSymlinkOutOfDateErrors(
        symlink=symlink,
        timestamp=timestamp,
        out_of_date_wrt_zip=is_stale(timestamp, zip_reference),
        out_of_date_wrt_dest=is_stale(timestamp, max_dest),
    )


def get_file_out_of_date_with_other_file_msg(file: Path, other_file: Path, msg_prefix: str) -> str:
    """Describe a file being older than one specific other file.

    The `other_file` branch is not dead defensiveness: a dependency carrying the
    missing-stage sentinel is reported through here, and naming the absent file is the
    whole message in that case. The `file` branch is a guard - the walk no longer pairs a
    present stage against a missing one, so it should not be reached, but the comparison
    below stats both files and would raise on a file that went away mid-run.

    Args:
        file: The out-of-date file.
        other_file: The newer file it should have been built from.
        msg_prefix: Prefix for the first line; later lines are indented to match.

    Returns:
        The multi-line message.

    """
    # Prefixed like every other finding. The first branch is the missing-stage sentinel's
    # message, so it is reached in an ordinary run - an unprefixed line here would flip the
    # exit code while slipping past any filter that greps for the prefix.
    if not other_file.is_file():
        return f'{msg_prefix}File "{other_file}" is missing.'
    if not file.is_file():
        return f'{msg_prefix}File "{file}" is missing.'

    blank_prefix = f"{' ':<{len(msg_prefix)}}"

    return (
        f'{msg_prefix}File "{get_abbrev_path(file)}"\n'
        f"{blank_prefix}is out of date with\n"
        f'{blank_prefix}file "{get_abbrev_path(other_file)}":\n'
        f"{blank_prefix}'{get_timestamp_str(file, *TIMESTAMP_SEPS)}'"
        f" < '{get_timestamp_str(other_file, *TIMESTAMP_SEPS)}'."
    )


def get_file_out_of_date_wrt_max_timestamp_msg(
    file: Path,
    max_reference: MaxTimestamp,
    msg_prefix: str,
) -> str:
    """Describe a file being older than the newest of a set of files.

    Args:
        file: The out-of-date file.
        max_reference: The newest input, and its timestamp.
        msg_prefix: Prefix for the first line; later lines are indented to match.

    Returns:
        The multi-line message.

    """
    blank_prefix = f"{' ':<{len(msg_prefix)}}"

    return (
        f'{msg_prefix}File "{get_abbrev_path(file)}"\n'
        f'{blank_prefix}is out of date WRT max file: "{get_abbrev_path(max_reference.file)}"\n'
        f"{blank_prefix}'{get_timestamp_str(file, *TIMESTAMP_SEPS)}'"
        f" < '{get_timestamp_as_str(max_reference.timestamp, *TIMESTAMP_SEPS)}'."
    )
