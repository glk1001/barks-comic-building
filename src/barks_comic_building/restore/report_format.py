"""Formatting shared by the things that report on a long run.

Both stages log an estimate as they go and have a status command that tabulates one, and
all four were formatting durations their own way. Kept together so the reports read alike
and a fix lands once.
"""

from __future__ import annotations

_SECONDS_PER_HOUR = 3600
_SECONDS_PER_MINUTE = 60


def format_duration(seconds: float) -> str:
    """Return a duration as hours and minutes.

    Args:
        seconds: The duration.

    Returns:
        Something like ``14h09m``, or ``--`` when there is nothing to report.

    """
    if seconds <= 0:
        return "--"

    hours, remainder = divmod(int(seconds), _SECONDS_PER_HOUR)
    minutes = remainder // _SECONDS_PER_MINUTE

    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def shorten_volume_title(volume_title: str) -> str:
    """Return just the story part of a volume's directory name.

    They are long enough to wreck a table otherwise - "Carl Barks Vol. 9 - Donald Duck -
    The Pixilated Parrot (Digital-Empire)" becomes "Donald Duck - The Pixilated Parrot".
    The volume number is already its own column, and the release group is not what these
    reports are about.

    Args:
        volume_title: The volume's full title.

    Returns:
        The shortened title.

    """
    short = volume_title
    if " - " in short:
        short = short.split(" - ", 1)[1]
    if short.endswith(")") and " (" in short:
        short = short.rsplit(" (", 1)[0]

    return short
