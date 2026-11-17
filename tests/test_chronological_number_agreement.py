"""Tests for the check that a built comic's info files record its current chronological number.

The artifact rename fix moves a built comic's dir, zip and symlinks onto a new
chronological number without rewriting any file contents, so the info files keep the
number the comic was built under. The check reports that as a warning - and only as a
warning: a renamed-but-not-rebuilt comic is correct for the reader, so it must not flip
the exit code.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from barks_build_comic_images.consts import DEST_SRCE_MAP_FILENAME, SUMMARY_FILENAME
from barks_fantagraphics.comics_consts import JSON_METADATA_FILENAME

from barks_comic_building.build.comics_integrity import (
    ComicsIntegrityChecker,
    recorded_chronological_numbers,
    stale_chronological_numbers,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def write_info_files(dest_dir: Path, num: int) -> None:
    """Write the three number-bearing info files as a build under `num` would."""
    dirname = f"{num:03d} Don Ault - Fantagraphics Introduction"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / SUMMARY_FILENAME).write_text(
        "Run Summary:\n"
        f'dest dir                 = "/comics/{dirname}"\n'
        f"chronological number     = {num}\n"
        'series                   = "Extras"\n'
    )
    (dest_dir / JSON_METADATA_FILENAME).write_text(
        json.dumps({"title": "x", "dest_dir": f"/comics/{dirname}"})
    )
    (dest_dir / DEST_SRCE_MAP_FILENAME).write_text(json.dumps({"dest_dirname": dirname}))


class TestRecordedNumbers:
    def test_reads_the_number_from_all_three_files(self, tmp_path: Path) -> None:
        write_info_files(tmp_path, 463)

        assert recorded_chronological_numbers(tmp_path) == {
            tmp_path / SUMMARY_FILENAME: 463,
            tmp_path / JSON_METADATA_FILENAME: 463,
            tmp_path / DEST_SRCE_MAP_FILENAME: 463,
        }

    def test_absent_or_unreadable_files_are_left_out(self, tmp_path: Path) -> None:
        # A missing info file is already its own finding; this check has nothing to
        # compare for it, and must not raise on one that is corrupt.
        (tmp_path / JSON_METADATA_FILENAME).write_text("{not json")
        (tmp_path / DEST_SRCE_MAP_FILENAME).write_text(json.dumps(["a", "list"]))

        assert recorded_chronological_numbers(tmp_path) == {}


class TestStaleNumbers:
    def test_a_rebuilt_comic_has_none(self, tmp_path: Path) -> None:
        write_info_files(tmp_path, 905)

        assert stale_chronological_numbers(tmp_path, 905) == []

    def test_a_renamed_comic_reports_every_file_with_the_old_number(self, tmp_path: Path) -> None:
        write_info_files(tmp_path, 463)

        assert stale_chronological_numbers(tmp_path, 905) == sorted(
            [
                (tmp_path / SUMMARY_FILENAME, 463),
                (tmp_path / JSON_METADATA_FILENAME, 463),
                (tmp_path / DEST_SRCE_MAP_FILENAME, 463),
            ]
        )


class TestIsAWarningNotAnError:
    def test_does_not_count_towards_the_exit_code(self, tmp_path: Path) -> None:
        errors = ComicsIntegrityChecker.make_out_of_date_errors("Fake Title")
        errors.expected_chronological_number = 905
        errors.stale_chronological_numbers = [(tmp_path / SUMMARY_FILENAME, 463)]

        assert not errors.is_error

    def test_is_printed_with_the_warning_prefix(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        errors = ComicsIntegrityChecker.make_out_of_date_errors("Fake Title")
        errors.expected_chronological_number = 905
        errors.stale_chronological_numbers = [(tmp_path / SUMMARY_FILENAME, 463)]

        ComicsIntegrityChecker.print_stale_chronological_number_warnings(errors)

        out = capsys.readouterr().out
        assert out.startswith('WARNING: For "Fake Title", the chronological number is 905')
        assert "records 463." in out
        assert "ERROR" not in out
