"""Keeping two restore runs out of the same work directory.

A run's work directory is where its stop request lives, and every run starts by clearing
any request left over from the last one. Two runs sharing a directory therefore share a
stop: the second to start withdrew a stop the first was still in the middle of honouring,
and the first carried on into its next batch. They also share memory, and one restore
already runs at the edge of what the machine has.

So a run takes a lock on its work directory for as long as it lasts, and a second run
that finds it taken refuses to start.

The lock is a kernel lock on a file rather than a pid written into one, because a run
that is killed leaves a pid file behind and a pid can be reused. A kernel lock goes when
the last process holding it does, so there is never a stale one to reason about. The
phase workers are forked from the run and inherit it, which is the right way round: a run
whose parent has died but whose workers are still writing is still in the directory.
"""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING

from barks_comic_building.restore.ledger_common import now

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

RUN_LOCK_FILENAME = "RUNNING"


class RunAlreadyActiveError(RuntimeError):
    """Another run holds the work directory."""


def get_run_lock_file(work_dir: Path) -> Path:
    """Return where the lock for runs using this work directory lives.

    Args:
        work_dir: The run's work directory.

    Returns:
        The lock file's path, whether or not it exists.

    """
    return work_dir / RUN_LOCK_FILENAME


@contextmanager
def hold_run_lock(work_dir: Path) -> Generator[None]:
    """Hold this work directory for one run, refusing if another run already does.

    The file is left behind afterwards. It is the lock on it that says a run is active,
    not its being there, and removing it would open a window in which a third run could
    lock a file the second had already unlinked.

    Args:
        work_dir: The run's work directory. Made if it is not there.

    Yields:
        Nothing. The directory is held until the block is left.

    Raises:
        RunAlreadyActiveError: If another run holds the directory, saying which.

    """
    work_dir.mkdir(parents=True, exist_ok=True)
    lock_file = get_run_lock_file(work_dir)

    # Opened for appending so that failing to get the lock does not wipe what the run
    # that holds it wrote about itself.
    with lock_file.open("a+", encoding="utf-8") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            f.seek(0)
            holder = f.read().strip() or "an unidentified run"
            msg = f'Another run is already using "{work_dir}": {holder}.'
            raise RunAlreadyActiveError(msg) from exc

        f.seek(0)
        f.truncate()
        f.write(f"pid {os.getpid()}, started {now()}\n")
        f.flush()

        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
