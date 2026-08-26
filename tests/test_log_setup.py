"""The errors-only sink's naming and its run id stamp."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from comic_utils.loguru_setup import LOGGER_SYS_NAME_KEY
from loguru import logger

from barks_comic_building.cli_setup import _error_filename
from barks_comic_building.log_setup import RUN_ID_KEY, bind_run_id, log_to_error_file_formatter

if TYPE_CHECKING:
    from collections.abc import Iterator

    from loguru import Record


@pytest.fixture
def captured_records() -> Iterator[list[Record]]:
    """Capture records from a throwaway sink, leaving the logger as it was found."""
    records: list[Record] = []

    logger.configure(extra={LOGGER_SYS_NAME_KEY: "test"}, patcher=None)
    sink_id = logger.add(lambda message: records.append(message.record), level="ERROR")

    yield records

    logger.remove(sink_id)
    logger.configure(patcher=None)


@pytest.mark.parametrize(
    ("log_filename", "expected"),
    [
        ("batch-restore.log", "batch-restore-errors.log"),
        ("barks-cmds.log", "barks-cmds-errors.log"),
        ("no-suffix", "no-suffix-errors"),
    ],
)
def test_error_filename_sits_beside_the_main_log(log_filename: str, expected: str) -> None:
    assert _error_filename(log_filename) == expected


def test_formatter_falls_back_when_logged_outside_a_run() -> None:
    # A message logged before the ledger is opened still has to format, so the run id
    # field is only referenced when something has bound one.
    assert log_to_error_file_formatter({"extra": {}}).startswith("<magenta>-</magenta> | ")


def test_formatter_leads_with_the_run_id() -> None:
    formatted = log_to_error_file_formatter({"extra": {RUN_ID_KEY: "an-id"}})

    assert formatted.startswith(f"<magenta>{{extra[{RUN_ID_KEY}]}}</magenta> | ")


def test_bind_run_id_stamps_records_without_dropping_sys_name(
    captured_records: list[Record],
) -> None:
    bind_run_id("a-run-id")
    logger.error("something failed")

    assert len(captured_records) == 1
    extra = captured_records[0]["extra"]
    assert extra[RUN_ID_KEY] == "a-run-id"
    # `logger.configure(extra=...)` would have replaced this, and the format strings that
    # reference it would have started raising instead of logging.
    assert extra[LOGGER_SYS_NAME_KEY] == "test"
