"""Project-specific CLI setup wrapping comic_utils.cli_setup."""

from pathlib import Path

from barks_fantagraphics.comics_helpers import get_comic_titles
from comic_utils.cli_setup import init_logging as _init_logging

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


__all__ = ["get_comic_titles", "init_logging"]
