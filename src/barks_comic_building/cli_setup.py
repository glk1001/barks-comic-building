"""Project-specific CLI setup wrapping comic_utils.cli_setup."""

from pathlib import Path

import typer
from barks_fantagraphics.comics_helpers import get_comic_titles
from comic_utils.cli_setup import init_logging as _init_logging
from intspan import intspan

import barks_comic_building.log_setup as _log_setup

_LOG_CONFIG = Path(__file__).parent / "resources" / "log-config.yaml"


def _error_filename(log_filename: str) -> str:
    """Return the errors-only companion name for a log filename.

    Args:
        log_filename: The main log's filename, e.g. "batch-restore.log".

    Returns:
        The error file's name, e.g. "batch-restore-errors.log".

    """
    path = Path(log_filename)

    return str(path.with_stem(f"{path.stem}-errors"))


def init_logging(app_logging_name: str, log_filename: str, log_level_str: str) -> None:
    """Configure loguru logging for this project's CLI entry points."""
    # Set before the config is loaded, since that is when the sink path is resolved.
    _log_setup.log_error_filename = _error_filename(log_filename)

    _init_logging(_log_setup, _LOG_CONFIG, app_logging_name, log_filename, log_level_str)


def get_single_volume(volumes_str: str) -> int:
    """Return the one volume a `--volume` option names.

    For the tools that work on one volume at a time. They used to `assert` this, so a
    missing or a multi-volume option ended in a traceback that named no option.

    Args:
        volumes_str: The `--volume` option, as given.

    Returns:
        The volume.

    Raises:
        typer.BadParameter: If the option is missing, is no volume list, or names more
            than one volume.

    """
    try:
        volumes = list(intspan(volumes_str))
    except ValueError as e:
        msg = f'--volume must be a single volume: "{volumes_str}".'
        raise typer.BadParameter(msg) from e

    if len(volumes) != 1:
        msg = f'--volume must be a single volume: "{volumes_str}".'
        raise typer.BadParameter(msg)

    return volumes[0]


def get_page_num(option: str, page_str: str) -> int:
    """Return the page number an option names.

    Args:
        option: The option's name, for the error message: "--page".
        page_str: The option's value, as given.

    Returns:
        The page number.

    Raises:
        typer.BadParameter: If the value is missing or is not a single page number.

    """
    if not page_str.isdecimal():
        msg = f'{option} must be a single page number: "{page_str}".'
        raise typer.BadParameter(msg)

    return int(page_str)


__all__ = ["get_comic_titles", "get_page_num", "get_single_volume", "init_logging"]
