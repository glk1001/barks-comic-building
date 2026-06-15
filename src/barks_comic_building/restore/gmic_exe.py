import subprocess
from collections import deque

from loguru import logger

# Number of trailing output lines to include in the error message when gmic fails.
_ERROR_OUTPUT_TAIL_LINES = 20


def run_gmic(params: list[str]) -> None:
    run_args = ["gmic", "-v", "+1", *params]

    logger.debug(f"Running gmic: {' '.join(run_args)}.")

    # Merge stderr into stdout so gmic's (stderr-bound) verbose and error messages are
    # captured and logged, and keep a bounded tail for diagnostics if the run fails.
    recent_output: deque[str] = deque(maxlen=_ERROR_OUTPUT_TAIL_LINES)
    process = subprocess.Popen(  # noqa: S603
        run_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip()
        if line:
            recent_output.append(line)
            logger.info(line)

    rc = process.wait()
    if rc != 0:
        tail = "\n".join(recent_output)
        msg = f"Gmic failed (exit code {rc}):\n{tail}"
        raise RuntimeError(msg)
