"""Tests that every finding the integrity report prints also fails the run.

The exit code used to be a separately-maintained boolean expression, assembled by hand
from twelve of the fifteen conditions the report can print. The other three - a stale
info file, and each symlink being older than the pages it points at - printed as ERROR
and left the exit code at 0. So `barks-check-build` would describe a stale tree and then
report success, and any script gating on it saw a clean build.

That is not a bug you fix once. A hand-written roll-up can always be one term short, and
nothing checks it against the printer. So `is_error` is derived, and the test below walks
every printable finding rather than a list someone remembered to update: adding a finding
to the report without making it fail the run is meant to be impossible, not merely
discouraged.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import get_origin

import pytest

from barks_comic_building.build.comics_integrity import ComicsIntegrityChecker, OutOfDateErrors
from barks_comic_building.build.utils import ZipOutOfDateErrors, ZipSymlinkOutOfDateErrors

TITLE = "Fake Title"

SRCE = Path("/fanta/restored/001.png")
DEST = Path("/comics/dest/images/001.jpg")
INFO_FILE = Path("/comics/dest/metadata.txt")
# A restorable page that resolved to the scan instead of its restored file - the
# synthetic collections' fallback, which no existence or timestamp check can see.
UNRESTORED_SRCE = Path("/fanta/fixes/images/501.jpg")
BOUNDS_OVERRIDE = Path("/fanta/fixes/images/bounded/001.jpg")
SEGMENTS = Path("/fanta/panel-segments/001.json")

# One representative payload per list-valued finding. `is_error` only asks whether the
# list is non-empty, so the contents matter only for being the right shape.
LIST_FINDINGS: dict[str, object] = {
    "srce_and_dest_files_missing": (SRCE, DEST),
    "srce_and_dest_files_out_of_date": (SRCE, DEST),
    "pages_built_without_restored_file": (UNRESTORED_SRCE, DEST),
    "stale_panel_segments": (BOUNDS_OVERRIDE, SEGMENTS),
    "dest_dir_files_missing": INFO_FILE,
    "dest_dir_files_out_of_date": INFO_FILE,
    "exception_errors": "the panel segments file could not be read",
    "unexpected_dest_image_files": Path("/comics/dest/images/stray.jpg"),
}

# The verdict dataclasses are frozen, so one instance per flag can be shared.
ZIP_FINDINGS = {
    "missing": ZipOutOfDateErrors(missing=True),
    "out_of_date_wrt_srce": ZipOutOfDateErrors(out_of_date_wrt_srce=True),
    "out_of_date_wrt_dest": ZipOutOfDateErrors(out_of_date_wrt_dest=True),
}

SYMLINK_FINDINGS = {
    "missing": ZipSymlinkOutOfDateErrors(missing=True),
    "out_of_date_wrt_zip": ZipSymlinkOutOfDateErrors(out_of_date_wrt_zip=True),
    "out_of_date_wrt_dest": ZipSymlinkOutOfDateErrors(out_of_date_wrt_dest=True),
}

SYMLINKS = ["series_zip_symlink_errors", "year_zip_symlink_errors"]


def no_findings() -> OutOfDateErrors:
    """Make an empty findings record, as a clean title produces."""
    return ComicsIntegrityChecker.make_out_of_date_errors(TITLE)


def flag_names(verdict: ZipOutOfDateErrors | ZipSymlinkOutOfDateErrors) -> set[str]:
    """Return the names of a verdict dataclass's boolean flags.

    Read off the dataclass rather than listed here, so that adding a flag to a verdict
    without covering it below fails the tripwire test instead of passing unnoticed.

    Args:
        verdict: A default-constructed verdict of the kind to inspect.

    Returns:
        Every boolean field name.

    """
    return {field.name for field in fields(verdict) if field.type in ("bool", bool)}


class TestEveryPrintableFindingFailsTheRun:
    """The correspondence the old roll-up broke, checked one finding at a time.

    Three of these used to assert False: `dest_dir_files_out_of_date`, and each
    symlink's out-of-date-versus-dest flag.
    """

    @pytest.mark.parametrize("finding", list(LIST_FINDINGS))
    def test_a_single_per_file_finding_is_an_error(self, finding: str) -> None:
        errors = no_findings()
        getattr(errors, finding).append(LIST_FINDINGS[finding])

        assert errors.is_error

    @pytest.mark.parametrize("flag", list(ZIP_FINDINGS))
    def test_a_single_zip_finding_is_an_error(self, flag: str) -> None:
        errors = no_findings()
        errors.zip_errors = ZIP_FINDINGS[flag]

        assert errors.is_error

    @pytest.mark.parametrize("which", SYMLINKS)
    @pytest.mark.parametrize("flag", list(SYMLINK_FINDINGS))
    def test_a_single_symlink_finding_is_an_error(self, which: str, flag: str) -> None:
        errors = no_findings()
        setattr(errors, which, SYMLINK_FINDINGS[flag])

        assert errors.is_error

    def test_a_title_with_nothing_wrong_is_not_an_error(self) -> None:
        assert not no_findings().is_error


class TestNoFlagGoesUncovered:
    """A tripwire for the next flag someone adds to a verdict.

    The roll-up drifted because it was a list maintained by hand. These tests read the
    fields off the dataclasses, so a new flag that nobody thought to include shows up
    here rather than in a report that exits 0.
    """

    def test_every_zip_flag_is_covered_above(self) -> None:
        assert flag_names(ZipOutOfDateErrors()) == set(ZIP_FINDINGS)

    def test_every_symlink_flag_is_covered_above(self) -> None:
        assert flag_names(ZipSymlinkOutOfDateErrors()) == set(SYMLINK_FINDINGS)

    def test_every_list_finding_is_covered_above(self) -> None:
        # The list-valued fields of the record. The two timestamp value objects and the
        # three verdicts are not lists, and the other tables cover those.
        list_fields = {
            field.name for field in fields(OutOfDateErrors) if get_origin(field.type) is list
        }

        assert list_fields == set(LIST_FINDINGS)


class TestTheReportAndTheExitCodeAgree:
    def test_a_per_file_finding_reaches_the_printed_section(self) -> None:
        # `file_findings` gates the per-file section of the report, and is one of the two
        # halves of `is_error`. They have to move together, which is the whole point of
        # deriving one from the other.
        errors = no_findings()
        errors.dest_dir_files_out_of_date.append(INFO_FILE)

        assert errors.file_findings
        assert errors.is_error

    def test_a_zip_finding_is_not_mistaken_for_a_per_file_one(self) -> None:
        errors = no_findings()
        errors.zip_errors = ZIP_FINDINGS["missing"]

        assert not errors.file_findings
        assert errors.zip_findings
        assert errors.is_error

    def test_an_unexpected_dest_image_is_neither_but_still_an_error(self) -> None:
        # Reported in its own section, so it belongs to neither group - and was the one
        # such finding the old roll-up did remember.
        errors = no_findings()
        errors.unexpected_dest_image_files.append(Path("stray.jpg"))

        assert not errors.file_findings
        assert not errors.zip_findings
        assert errors.is_error
