"""Project-specific CLI setup wrapping comic_utils.cli_setup."""

from pathlib import Path

from barks_fantagraphics.comics_helpers import get_comic_titles
from comic_utils.cli_setup import init_logging as _init_logging

import barks_comic_building.log_setup as _log_setup

_LOG_CONFIG = Path(__file__).parent / "resources" / "log-config.yaml"


def init_logging(app_logging_name: str, log_filename: str, log_level_str: str) -> None:
    """Configure loguru logging for this project's CLI entry points."""
    _init_logging(_log_setup, _LOG_CONFIG, app_logging_name, log_filename, log_level_str)


__all__ = ["get_comic_titles", "init_logging"]
