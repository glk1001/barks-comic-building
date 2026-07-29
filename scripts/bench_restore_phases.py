"""Measure how the two gmic restore steps scale, to pick the phase worker counts.

Smoothing and inpainting are between them about ninety percent of the restore's wall
clock, and neither scales anything like linearly with the number of pages run at once:
six concurrent smooths were measured returning only about 1.5x the throughput of one, and
four concurrent inpaints about 2.3x.

There are two candidate explanations and they call for opposite fixes. gmic parallelises
internally with OpenMP and takes every core it can see, so six concurrent smooths ask for
ninety six threads on sixteen cores - if that oversubscription is the problem, capping the
threads per process wins back most of the loss. If instead the machine is out of memory
bandwidth - a 5700G has two DDR4 channels feeding sixteen cores, and these are 100
megapixel images - then no arrangement of workers and threads helps much, and the honest
answer is that the current settings are already close to the ceiling.

Only a measurement separates them, so this walks the grid and prints the throughput.

Run on 2026-07-29 against the smooth step on this machine, the answer was bandwidth:

    workers |  omp=2   omp=4   omp=16
          6 |     27.3    29.7     28.6    pages/hour

An 8.8% spread across a 5.7x change in thread count, and not monotonic. The uncapped cell
also agrees with what a real restore measured (29.0 pages/hour), which is the check that
the harness is measuring the right thing at all. So the thread caps in _PHASES are left
off, and this script is kept for the next time the hardware or the gmic version changes.

Usage:
    uv run scripts/bench_restore_phases.py --step smooth --work-file <a -color-removed.png>
    uv run scripts/bench_restore_phases.py --step inpaint --work-file <a -color-removed.png> \
        --upscayl-file <the matching upscayled page>

Run it on an idle machine: anything else using the cores makes the numbers meaningless.
That is how a previous measurement in this project went wrong.
"""

# ruff: noqa: T201

import concurrent.futures
import os
import tempfile
import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from barks_comic_building.restore.inpaint import inpaint_image_file
from barks_comic_building.restore.smooth_image import smooth_image_file


class Step(StrEnum):
    """Which of the two expensive gmic steps to measure."""

    SMOOTH = "smooth"
    INPAINT = "inpaint"


DEFAULT_WORKERS = "1,2,3,4,6,8"
DEFAULT_THREADS = "1,2,4,8,16"


def _run_one(  # noqa: PLR0913
    step: Step, in_file: Path, upscayl_file: Path | None, out_dir: Path, index: int, threads: int
) -> float:
    """Run the step once with a thread cap, returning how long it took."""
    os.environ["OMP_NUM_THREADS"] = str(threads)

    start = time.time()
    if step is Step.SMOOTH:
        smooth_image_file(in_file, out_dir / f"smoothed-{index}.png")
    else:
        assert upscayl_file is not None
        inpaint_image_file(
            out_dir, f"bench-{index}", upscayl_file, in_file, out_dir / f"ip-{index}.png"
        )

    return time.time() - start


def _time_cell(  # noqa: PLR0913
    step: Step,
    in_file: Path,
    upscayl_file: Path | None,
    out_dir: Path,
    num_workers: int,
    threads: int,
) -> tuple[float, float]:
    """Run `num_workers` copies of the step at once.

    Returns:
        The wall clock for the whole cell, and the throughput in pages per hour.

    """
    start = time.time()
    with concurrent.futures.ProcessPoolExecutor(num_workers) as executor:
        futures = [
            executor.submit(_run_one, step, in_file, upscayl_file, out_dir, i, threads)
            for i in range(num_workers)
        ]
        for future in futures:
            future.result()

    wall = time.time() - start

    return wall, num_workers * 3600.0 / wall


app = typer.Typer()


@app.command(help="Measure how the gmic restore steps scale with workers and threads")
def main(
    work_file: Annotated[
        Path,
        typer.Option(help="A '-color-removed.png' work file to run the step against."),
    ],
    step: Annotated[Step, typer.Option(help="Which step to measure.")] = Step.SMOOTH,
    upscayl_file: Annotated[
        Path | None,
        typer.Option(help="The matching upscayled page. Required for the inpaint step."),
    ] = None,
    workers_str: Annotated[
        str, typer.Option("--workers", help="Comma separated worker counts.")
    ] = DEFAULT_WORKERS,
    threads_str: Annotated[
        str, typer.Option("--threads", help="Comma separated OMP_NUM_THREADS values.")
    ] = DEFAULT_THREADS,
) -> None:
    if not work_file.is_file():
        msg = f'Could not find work file: "{work_file}".'
        raise typer.BadParameter(msg)
    if step is Step.INPAINT and (upscayl_file is None or not upscayl_file.is_file()):
        msg = "The inpaint step needs --upscayl-file."
        raise typer.BadParameter(msg)

    workers = [int(w) for w in workers_str.split(",")]
    threads = [int(t) for t in threads_str.split(",")]

    print(f"Step: {step}. Cores: {os.process_cpu_count()}.")
    print(f"Input: {work_file}  ({work_file.stat().st_size / 1e6:.0f}MB)")
    print(f"{len(workers) * len(threads)} cell(s), each many minutes. Higher pages/hour wins.\n")

    # A cell is many minutes, so each one is reported as it lands rather than the whole
    # grid appearing at the end. A run that says nothing for forty minutes is
    # indistinguishable from one that has hung.
    print(f"{'workers':>7} {'omp':>5} {'wall':>9} {'pages/hr':>9}")
    print("-" * 33)

    best = (0.0, 0, 0)
    grid: dict[int, list[str]] = {}
    with tempfile.TemporaryDirectory() as temp_dir:
        out_dir = Path(temp_dir)
        for num_workers in workers:
            grid[num_workers] = []
            for num_threads in threads:
                wall, rate = _time_cell(
                    step, work_file, upscayl_file, out_dir, num_workers, num_threads
                )
                print(f"{num_workers:>7} {num_threads:>5} {wall:>8.0f}s {rate:>9.1f}", flush=True)

                grid[num_workers].append(f"{rate:7.1f}")
                if rate > best[0]:
                    best = (rate, num_workers, num_threads)

                # Keep the scratch from growing across the grid.
                for leftover in out_dir.iterdir():
                    leftover.unlink(missing_ok=True)

    print("\nThroughput in pages/hour:\n")
    header = "workers |" + "".join(f"  omp={t:<2}" for t in threads)
    print(header)
    print("-" * len(header))
    for num_workers, cells in grid.items():
        print(f"{num_workers:7} |" + "".join(f"  {c}" for c in cells))

    print(f"\nBest: {best[0]:.1f} pages/hour at {best[1]} worker(s), OMP_NUM_THREADS={best[2]}.")
    print("Put that pair into _PHASES in restore/batch_restore_pipeline.py,")
    print("with a comment recording this measurement.")


if __name__ == "__main__":
    app()
