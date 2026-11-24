"""Plot one value a year, for the yearly page count and payments reports."""
# ruff: noqa: T201, ERA001

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


# The size the yearly reports are plotted at. The dpi is a common one for screens.
REPORT_WIDTH_PX = 1000
REPORT_HEIGHT_PX = 732
REPORT_DPI = 100


def create_yearly_plot(  # noqa: PLR0913
    plot_title: str,
    years: Sequence[int],
    values: Sequence[float],
    output_filename: str | Path = "barks-yearly-page-count.png",
    width_px: int = 1800,
    height_px: int = 1050,
    dpi: int = 150,
) -> None:
    """Create, save, and display a plot of one value a year.

    Args:
        plot_title: The title to print above the plot.
        years: The years, for the x-axis.
        values: Each year's value, for the y-axis.
        output_filename: The file to save the plot to.
        width_px: The width of the saved image in pixels.
        height_px: The height of the saved image in pixels.
        dpi: The resolution, in dots per inch, of the saved image.

    """
    if len(years) != len(values):
        print("Error: The lists of years and values must have the same number of elements.")
        return

    # Calculate the figure size in inches to achieve the desired pixel dimensions
    # figsize = (width_pixels / dpi, height_pixels / dpi)
    fig_width_in = width_px / dpi
    fig_height_in = height_px / dpi

    # Use a nice style for the plot
    plt.style.use("seaborn-v0_8-whitegrid")

    # Create a figure with the calculated size
    _fig, ax = plt.subplots(figsize=(fig_width_in, fig_height_in), dpi=dpi)

    # --- Plot the data ---
    ax.plot(
        years,
        values,
        color="green",
        linestyle="solid",
        marker="o",
        markerfacecolor="red",
        markersize=10,
        label="Yearly Page Count",
    )

    # --- Customize the plot for clarity ---
    ax.set_title(
        plot_title,
        fontsize=18,
        fontweight="bold",
        pad=10,
    )
    # ax.set_xlabel("Year", color="blue", fontsize=14, fontweight="bold", labelpad=10)
    # ax.set_ylabel("Count", color="blue", fontsize=14, fontweight="bold", labelpad=5)

    # Set the x-axis ticks to appear every 2 years to avoid clutter
    ax.set_xticks(np.arange(min(years), max(years) + 1, 2))
    plt.xticks(rotation=45, ha="right", fontweight="bold")
    plt.yticks(fontweight="bold")

    # Ensure the y-axis starts at 0
    if all(v >= 0 for v in values):
        ax.set_ylim(bottom=0)

    # Add a legend to identify the data series
    # ax.legend()

    # Adjust layout to make sure everything fits without being cut off
    plt.tight_layout()

    # --- Save the plot to a file ---
    try:
        # The dpi here should match the one used for the figure for predictable results
        plt.savefig(output_filename, dpi=dpi)
        print(f"Plot successfully saved to {output_filename} ({width_px}x{height_px}px)")
    except Exception as e:  # noqa: BLE001
        print(f"Error saving plot: {e}")

    # Display the plot in a new window
    plt.show()


def show_yearly_report_plot(
    plot_title: str, years: Sequence[int], values: Sequence[float], output_filename: str | Path
) -> None:
    """Plot a yearly report at the size the reports are made at, save it and show it.

    Args:
        plot_title: The title to print above the plot.
        years: The years, for the x-axis.
        values: Each year's value, for the y-axis.
        output_filename: The file to save the plot to.

    """
    print(f"Plotting {len(years)} data points...")

    create_yearly_plot(
        plot_title,
        years=years,
        values=values,
        output_filename=output_filename,
        width_px=REPORT_WIDTH_PX,
        height_px=REPORT_HEIGHT_PX,
        dpi=REPORT_DPI,
    )
