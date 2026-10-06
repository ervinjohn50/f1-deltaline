"""Track map coloured by which driver was faster in each mini-sector."""

import fastf1.plotting
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

FALLBACK_COLOR = "#e0e0e0"  # used when both drivers share a team colour


def driver_colors(session, driver_a, driver_b):
    color_a = fastf1.plotting.get_driver_color(driver_a, session)
    color_b = fastf1.plotting.get_driver_color(driver_b, session)
    if color_a.lower() == color_b.lower():
        color_b = FALLBACK_COLOR
    return color_a, color_b


def plot_comparison(tel, sample_winners, drivers, colors, lap_times, title):
    """Draw the track from tel's X/Y, each segment coloured by its sector winner."""
    points = np.column_stack([tel["X"], tel["Y"]]).reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    segment_colors = [colors[w] for w in sample_winners[:-1]]

    fig, ax = plt.subplots(figsize=(10, 8), facecolor="#15151e")
    ax.set_facecolor("#15151e")
    ax.add_collection(LineCollection(segments, colors=segment_colors, linewidths=6,
                                     capstyle="round"))
    ax.autoscale()
    ax.set_aspect("equal")
    ax.axis("off")

    handles = [
        Line2D([0], [0], color=colors[i], lw=6,
               label=f"{drivers[i]}  {format_lap_time(lap_times[i])}")
        for i in range(2)
    ]
    ax.legend(handles=handles, loc="lower right", facecolor="#15151e",
              edgecolor="#444", labelcolor="white", fontsize=11)
    ax.set_title(title, color="white", fontsize=14, pad=16)
    fig.tight_layout()
    return fig


def format_lap_time(seconds):
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:06.3f}"
