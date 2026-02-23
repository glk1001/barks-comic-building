import subprocess

from loguru import logger


def run_gmic(params: list[str]) -> None:
    gmic_path = "gmic"
    run_args = [gmic_path, "-v", "+1"]
    run_args.extend(params)

    logger.debug(f"Running gmic: {' '.join(run_args)}.")

    process = subprocess.Popen(run_args, stdout=subprocess.PIPE, text=True)  # noqa: S603

    while True:
        output = process.stdout.readline()  # ty: ignore[possibly-missing-attribute]
        if output == "" and process.poll() is not None:
            break
        if output:
            logger.info(output.strip())

    rc = process.poll()
    if rc != 0:
        msg = "Gmic failed."
        raise RuntimeError(msg)
