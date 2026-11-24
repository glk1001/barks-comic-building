"""Test that every console script in `pyproject.toml` points at something that exists.

`barks-silent-night-restore` outlived its module by months: the file was deleted, the
`[project.scripts]` entry stayed, and nothing noticed until someone ran it and got a
`ModuleNotFoundError`. An entry point is only resolved when it is run, so no linter or
type checker sees a dangling one.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest
import typer

PYPROJECT_FILE = Path(__file__).parent.parent / "pyproject.toml"

with PYPROJECT_FILE.open("rb") as _f:
    SCRIPTS: dict[str, str] = tomllib.load(_f)["project"]["scripts"]


def test_there_are_scripts_to_check() -> None:
    assert SCRIPTS


@pytest.mark.parametrize("script", sorted(SCRIPTS))
def test_a_console_script_resolves_to_a_typer_app(script: str) -> None:
    module_name, _, attribute = SCRIPTS[script].partition(":")

    module = importlib.import_module(module_name)

    assert isinstance(getattr(module, attribute), typer.Typer)
