# ruff: noqa: T201, ERA001, ANN001

import matplotlib.pyplot as plt
import numpy as np

APP_LOGGING_NAME = "ygra"


def create_yearly_plot(  # noqa: D417, PLR0913
    plot_title: str,
    years,
    values,
    output_filename="barks-yearly-page-count.png",
    width_px=1800,
    height_px=1050,
    dpi=150,
) -> None:
    """Create, save, and display a plot of integer values against a range of years.

    Args:
        plot_title
        years (list): A list of years for the x-axis.
        values (list): A list of integer values for the y-axis.
        output_filename (str): The name of the file to save the plot to.
        width_px (int): The desired width of the output image in pixels.
        height_px (int): The desired height of the output image in pixels.
        dpi (int): The resolution (dots per inch) for the output image.

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
    fig, ax = plt.subplots(figsize=(fig_width_in, fig_height_in), dpi=dpi)

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


if __name__ == "__main__":
    start_year = 1942
    end_year = 1966
    title = f"Yearly Page Count from {start_year} to {end_year}"
    years_data = list(range(start_year, end_year + 1))

    values_data = [
        52,
        184,
        174,
        177,
        266,
        302,
        289,
        332,
        327,
        265,
        318,
        308,
        334,
        369,
        351,
        385,
        384,
        172,
        269,
        236,
        280,
        225,
        229,
        180,
        127,
    ]

    print(f"Plotting {len(years_data)} data points...")

    create_yearly_plot(
        title,
        years=years_data,
        values=values_data,
        output_filename="/tmp/barks-yearly-page-counts.png",  # noqa: S108
        width_px=1000,
        height_px=732,
        dpi=100,  # A common DPI for screen resolutions
    )
