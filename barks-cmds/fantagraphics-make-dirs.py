import sys
from pathlib import Path

from barks_fantagraphics.comics_cmd_args import CmdArgs
from loguru import logger
from loguru_config import LoguruConfig

if __name__ == "__main__":
    cmd_args = CmdArgs("Make required Fantagraphics directories.")
    args_ok, error_msg = cmd_args.args_are_valid()
    if not args_ok:
        logger.error(error_msg)
        sys.exit(1)

    # Global variable accessed by loguru-config.
    log_level = cmd_args.get_log_level()
    LoguruConfig.load(Path(__file__).parent / "log-config.yaml")

    comics_database = cmd_args.get_comics_database()

    comics_database.make_all_fantagraphics_directories()
