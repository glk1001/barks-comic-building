"""Shared loguru-config globals, referenced by log-config.yaml via ext:// protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from comic_utils.loguru_setup import log_to_file_formatter
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

APP_LOGGING_NAME: str = "main"
log_level: str = "DEBUG"
log_filename: str = "barks-comic-building.log"

# The errors-only companion to `log_filename`. A run logs a handful of errors among tens
# of thousands of lines, and the main sink rotates at 10 MB, so a long run can rotate its
# own errors out of the file you would go looking in. This one does not rotate: at a few
# lines a run it holds years of them, which is the point - it is the only place the
# errors of one run sit next to the errors of the run before.
log_error_filename: str = "barks-comic-building-errors.log"

# The key a run id is carried under in loguru's `extra`.
RUN_ID_KEY = "run_id"

# What the error file shows for a message logged outside any run: before the ledger is
# opened, or from a command that keeps no ledger at all.
_NO_RUN_ID = "-"


def log_to_error_file_formatter(record: Mapping[str, Any]) -> str:
    """Format an error-file line, led by the run id so it joins to the ledger.

    The ledger says which page failed and at which step; this file says why. Leading with
    the run id is what lets one be looked up from the other.

    Args:
        record: The record being formatted. Typed as the mapping this reads rather than
            loguru's `Record`, which is a TypedDict a caller cannot part-fill.

    Returns:
        The loguru format string for it.

    """
    run_id = f"{{extra[{RUN_ID_KEY}]}}" if RUN_ID_KEY in record["extra"] else _NO_RUN_ID

    return f"<magenta>{run_id}</magenta> | " + log_to_file_formatter(record)


def bind_run_id(run_id: str) -> None:
    """Stamp every record logged from here on with the run it belongs to.

    Applied as a patcher rather than through `logger.configure(extra=...)`, which would
    replace the whole `extra` dict and take `sys_name` with it. Phase workers are forked
    after this is called, so their records carry the run id too.

    Args:
        run_id: The ledger run id to stamp.

    """
    logger.configure(patcher=lambda record: record["extra"].setdefault(RUN_ID_KEY, run_id))
