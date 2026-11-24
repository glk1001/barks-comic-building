"""Tests for keeping two restore runs out of the same work directory."""

from __future__ import annotations

import multiprocessing
import os
from typing import TYPE_CHECKING

import pytest

from barks_comic_building.restore.run_lock import (
    RunAlreadyActiveError,
    get_run_lock_file,
    hold_run_lock,
)

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from pathlib import Path


def try_to_run(work_dir: Path, result: Connection) -> None:
    """Try to hold the work directory from another process, and say how it went."""
    try:
        with hold_run_lock(work_dir):
            result.send("held")
    except RunAlreadyActiveError as exc:
        result.send(str(exc))


def run_in_another_process(work_dir: Path) -> str:
    """Return what a second process was told when it tried to start a run here."""
    receiver, sender = multiprocessing.Pipe(duplex=False)
    process = multiprocessing.get_context("spawn").Process(
        target=try_to_run, args=(work_dir, sender)
    )
    process.start()
    process.join(timeout=30)

    return receiver.recv() if receiver.poll() else "no answer"


def test_a_second_run_is_refused_while_the_first_is_going(tmp_path: Path) -> None:
    with hold_run_lock(tmp_path):
        answer = run_in_another_process(tmp_path)

    assert "Another run is already using" in answer
    assert f"pid {os.getpid()}" in answer


def test_a_run_can_start_once_the_last_one_has_finished(tmp_path: Path) -> None:
    with hold_run_lock(tmp_path):
        pass

    assert run_in_another_process(tmp_path) == "held"


def test_a_run_that_was_killed_leaves_nothing_to_clear(tmp_path: Path) -> None:
    """Its file is still there, naming a pid, but nothing holds the lock on it."""
    get_run_lock_file(tmp_path).write_text("pid 1, started 2026-07-29T12:00:00+10:00\n")

    with hold_run_lock(tmp_path):
        assert f"pid {os.getpid()}" in get_run_lock_file(tmp_path).read_text()


def test_a_run_that_raises_still_lets_go(tmp_path: Path) -> None:
    msg = "the run fell over"
    with pytest.raises(RuntimeError, match=msg), hold_run_lock(tmp_path):
        raise RuntimeError(msg)

    assert run_in_another_process(tmp_path) == "held"


def test_being_refused_does_not_wipe_what_the_holder_wrote(tmp_path: Path) -> None:
    with hold_run_lock(tmp_path):
        before = get_run_lock_file(tmp_path).read_text()
        run_in_another_process(tmp_path)

        assert get_run_lock_file(tmp_path).read_text() == before


def test_the_work_directory_is_made_if_needed(tmp_path: Path) -> None:
    with hold_run_lock(tmp_path / "not" / "yet"):
        assert get_run_lock_file(tmp_path / "not" / "yet").is_file()
