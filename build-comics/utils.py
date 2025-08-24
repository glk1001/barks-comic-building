import os

from barks_fantagraphics.comics_utils import (
    dest_file_is_older_than_srce,
    file_is_older_than_timestamp,
    get_abbrev_path,
    get_timestamp_as_str,
    get_timestamp_str,
)
from loguru import logger

DATE_SEP = "-"
DATE_TIME_SEP = " "
HOUR_SEP = ":"


def get_shorter_ini_filename(ini_file: str) -> str:
    return os.path.basename(ini_file)


def get_list_of_numbers(list_str: str) -> list[int]:
    if not list_str:
        return []
    if "-" not in list_str:
        return [int(list_str)]

    p_start, p_end = list_str.split("-")
    return list(range(int(p_start), int(p_end) + 1))


def dest_file_is_out_of_date_wrt_srce(srce_file: str, dest_file: str) -> bool:
    if not os.path.isfile(dest_file):
        logger.debug(f'Dest file "{dest_file}" not found.')
        return True

    if dest_file_is_older_than_srce(srce_file, dest_file, include_missing_dest=False):
        logger.debug(get_file_out_of_date_with_other_file_msg(dest_file, srce_file, ""))
        return True

    return False


def zip_file_is_out_of_date_wrt_dest(
    zip_file: str,
    max_dest_file: str,
    max_dest_timestamp: float,
) -> bool:
    if not os.path.isfile(zip_file):
        logger.debug(f'Dest zip file "{zip_file}" not found.')
        return False

    if file_is_older_than_timestamp(zip_file, max_dest_timestamp):
        logger.debug(
            get_file_out_of_date_wrt_max_timestamp_msg(
                zip_file,
                max_dest_file,
                max_dest_timestamp,
                "",
            ),
        )
        return True

    return False


def symlink_is_out_of_date_wrt_dest(symlink: str, max_dest_timestamp: float) -> bool:
    if file_is_older_than_timestamp(symlink, max_dest_timestamp):
        logger.debug(get_symlink_out_of_date_wrt_max_dest_msg(symlink, max_dest_timestamp))
        return True

    return False


def symlink_is_out_of_date_wrt_zip(symlink: str, zip_file: str) -> bool:
    if not os.path.islink(symlink):
        logger.debug(f'Dest file "{symlink}" not found.')
        return False

    if dest_file_is_older_than_srce(zip_file, symlink, include_missing_dest=False):
        logger.debug(get_symlink_out_of_date_wrt_zip_msg(symlink, zip_file))
        return True

    return False


def get_file_out_of_date_with_other_file_msg(file: str, other_file: str, msg_prefix: str) -> str:
    if not os.path.isfile(other_file):
        return f'File "{other_file}" is missing.'
    if not os.path.isfile(file):
        return f'File "{file}" is missing.'

    blank_prefix = f"{' ':<{len(msg_prefix)}}"

    return (
        f'{msg_prefix}File "{get_abbrev_path(file)}"\n'
        f"{blank_prefix}is out of date with\n"
        f'{blank_prefix}file "{get_abbrev_path(other_file)}":\n'
        f"{blank_prefix}'{get_timestamp_str(file, DATE_SEP, DATE_TIME_SEP, HOUR_SEP)}'"
        f" < '{get_timestamp_str(other_file, DATE_SEP, DATE_TIME_SEP, HOUR_SEP)}'."
    )


def get_file_out_of_date_wrt_max_timestamp_msg(
    file: str,
    max_file: str,
    max_timestamp: float,
    msg_prefix: str,
) -> str:
    blank_prefix = f"{' ':<{len(msg_prefix)}}"

    return (
        f'{msg_prefix}File "{get_abbrev_path(file)}"\n'
        f'{blank_prefix}is out of date WRT max file: "{get_abbrev_path(max_file)}"\n'
        f"{blank_prefix}'{get_timestamp_str(file, DATE_SEP, DATE_TIME_SEP, HOUR_SEP)}'"
        f" < '{get_timestamp_as_str(max_timestamp, DATE_SEP, DATE_TIME_SEP, HOUR_SEP)}'."
    )


def get_zip_file_out_of_date_wrt_max_dest_msg(zip_file: str, max_dest_timestamp: float) -> str:
    return (
        f"Zip file \"{get_abbrev_path(zip_file)}\" timestamp '{get_timestamp_str(zip_file)}',"
        f" is out of date WRT"
        f" max dest page timestamp '{get_timestamp_as_str(max_dest_timestamp)}'."
    )


def get_symlink_out_of_date_wrt_zip_msg(symlink: str, zip_file: str) -> str:
    return (
        f"Symlink \"{get_abbrev_path(symlink)}\" timestamp '{get_timestamp_str(symlink)}',"
        f" is out of date WRT"
        f' zip file "{zip_file}" ({get_timestamp_str(zip_file)}).'
    )


def get_symlink_out_of_date_wrt_max_dest_msg(symlink: str, max_dest_timestamp: float) -> str:
    return (
        f"Symlink \"{get_abbrev_path(symlink)}\" timestamp '{get_timestamp_str(symlink)}',"
        f" is out of date WRT"
        f" max dest image timestamp '{get_timestamp_as_str(max_dest_timestamp)}'."
    )
