"""The parts a jsonl ledger needs whichever stage is writing it.

Both the restore and the upscale keep an append-only record of what they did, in the same
shape and for the same reasons, and the awkward parts of that - surviving a hard kill
mid-write, generating a run id that cannot collide, noting which commit produced a record
- are not specific to either. They live here so that a fix to one is a fix to both.

The record shapes themselves stay with each stage, since they have little in common
beyond the run and page split.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Self

RECORD_TYPE_RUN = "run"
RECORD_TYPE_PAGE = "page"

OUTCOME_OK = "ok"
OUTCOME_FAILED = "failed"
OUTCOME_COPIED = "copied"

# Started, and left unfinished because the run was asked to stop. Not a failure: what
# the page wrote is intact and the next run carries on from it, so reports that list
# what went wrong should leave these out.
OUTCOME_STOPPED = "stopped"
# A page that was already there, so this run did nothing to it. Recorded rather than
# passed over so that the ledger accounts for every page a run looked at.
OUTCOME_PRESENT = "present"


def now() -> str:
    """Return the current time as an iso timestamp.

    Local time with its utc offset, so it reads naturally and is still unambiguous across
    the daylight saving change a run this long will cross.

    Returns:
        The timestamp, to the second.

    """
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get_git_commit() -> str:
    """Return the short commit this code is running from, or an empty string.

    Returns:
        The abbreviated hash, or "" if git is unavailable or this is not a checkout.

    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return ""

    return result.stdout.strip()


def new_run_id(started: str) -> str:
    """Return an id no other run can share.

    The timestamp and pid alone are not unique - two runs started in the same second, or a
    reused pid, would collide, and since runs are read back into a dict keyed by this the
    later one would silently swallow the earlier. Losing a record is the one thing an
    append-only ledger must not do, so a random suffix settles it.

    Args:
        started: The run's start timestamp.

    Returns:
        The run id.

    """
    return f"{started}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


def get_host() -> str:
    """Return the machine's hostname."""
    return socket.gethostname()


def _ends_mid_line(path: Path) -> bool:
    """Return whether a file has content that does not finish with a newline."""
    try:
        with path.open("rb") as f:
            f.seek(-1, os.SEEK_END)
            return f.read(1) != b"\n"
    except OSError:
        # Missing, or empty: either way there is no unfinished line to close off.
        return False


class JsonlWriter:
    """Appends json records, one per line, flushing as it goes.

    Used as a context manager so the handle is closed on the way out, whatever the run
    did. Lines are flushed as they are written so that a ledger stays usable after a hard
    kill.
    """

    def __init__(self, ledger_file: Path) -> None:
        """Note where to append. The file is not opened until the context is entered.

        Args:
            ledger_file: Where to append. Parent directories are created on entry.

        """
        self.ledger_file = ledger_file
        self._file = None

    def __enter__(self) -> Self:
        """Open the ledger file for appending, on a line of its own.

        A run killed part way through a write leaves a last line with no newline. The
        next run's first record - the one that says which recipe its pages were made
        with - would be glued onto that fragment, and the two would be skipped together
        as one unreadable line. So a file that does not end in a newline is given one
        first, which leaves the fragment the only thing lost.
        """
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        ends_mid_line = _ends_mid_line(self.ledger_file)
        self._file = self.ledger_file.open("a", encoding="utf-8")
        if ends_mid_line:
            self._file.write("\n")
        return self

    def __exit__(self, *_exc: object) -> None:
        """Close the ledger file, however the run ended."""
        if self._file is not None:
            self._file.close()
            self._file = None

    def write(self, record: dict[str, Any]) -> None:
        """Append one record.

        Args:
            record: The record, which must be json serialisable.

        Raises:
            RuntimeError: If used outside its context manager, when there is nothing open
                to write to and the record would otherwise be lost silently.

        """
        if self._file is None:
            msg = "Ledger writer used outside its context manager."
            raise RuntimeError(msg)

        self._file.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._file.flush()


def read_records(path: Path, schema: int) -> Iterator[dict[str, Any]]:
    """Yield the readable records of a ledger.

    Malformed lines are skipped rather than raising - a ledger that survived a hard kill
    mid-write has to stay readable, and one bad line should not cost the other thousands.
    That includes a line that is sound json and not a record: a flipped bit or a hand
    edit can leave a bare list or string, and every reader downstream asks a record for
    its fields. Records written by a newer schema are skipped too, since this code
    cannot know what their fields mean.

    Args:
        path: The ledger to read. A file that does not exist yields nothing.
        schema: The newest schema this reader understands.

    Yields:
        Each record that parsed.

    """
    if not path.is_file():
        return

    num_skipped = 0
    with path.open(encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    msg = f"a json {type(record).__name__}, not a record"
                    raise TypeError(msg)  # noqa: TRY301
                record_schema = record.get("schema", 0)
                if not isinstance(record_schema, int):
                    msg = f"schema {record_schema!r} is not a number"
                    raise TypeError(msg)  # noqa: TRY301
                if record_schema > schema:
                    msg = f"schema {record_schema} is newer than {schema}"
                    raise ValueError(msg)  # noqa: TRY301
            except (TypeError, ValueError) as exc:
                num_skipped += 1
                logger.debug(f'Skipping ledger line {line_num} of "{path}": {exc}.')
                continue

            yield record

    if num_skipped:
        logger.warning(f'Skipped {num_skipped} unreadable line(s) in "{path}".')
