"""Comparison figure: track map coloured by sector winner, plus gap and input traces."""

import fastf1.plotting
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec
from matplotlib.lines import Line2D

FALLBACK_COLOR = "#e0e0e0"  # used when both drivers share a team colour
BACKGROUND = "#15151e"
TEXT = "#f0f0f0"
MUTED = "#8a8a99"
GRID = "#2c2c3a"
CORNER_LABEL_OFFSET = 600  # track units are 1/10 m, so about 60 m off the racing line


def driver_colors(session, driver_a, driver_b):
    color_a = fastf1.plotting.get_driver_color(driver_a, session)
    color_b = fastf1.plotting.get_driver_color(driver_b, session)
    if color_a.lower() == color_b.lower():
        color_b = FALLBACK_COLOR
    return color_a, color_b


def plot_comparison(track, sample_winners, distance_m, delta, traces,
                    labels, colors, legend_labels, title, corners=(), note="",
                    key_moments=()):
    """Map on the left; gap, speed, throttle and brake stacked on the right.

    track: telemetry with X/Y for drawing the circuit.
    sample_winners: 0/1 per track sample, who won that sample's mini-sector.
    distance_m: shared x-axis in metres for the traces.
    delta: running gap in seconds (positive = driver A ahead).
    traces: {"Speed (km/h)": (values_a, values_b), ...}
    labels: short name for each lap, e.g. "LEC" or "VER L5".
    legend_labels: full legend text for each lap, including lap time.
    note: optional extra lines shown under the legend.
    key_moments: biggest gains from explain_lap, numbered on the gap chart and
        written out along the bottom.
    """
    fig = plt.figure(figsize=(16, 10), facecolor=BACKGROUND)
    # Gap chart first, then one row per trace; brake is on/off so it gets less height.
    height_ratios = [1.3] + [0.5 if "Brake" in label else 1.0 for label in traces]
    grid = GridSpec(len(height_ratios), 2, figure=fig, width_ratios=[1, 1.35],
                    height_ratios=height_ratios, wspace=0.08, hspace=0.12)

    # Left column: map on top, legend in its own row below so it never covers the track.
    left = GridSpecFromSubplotSpec(2, 1, subplot_spec=grid[:, 0], height_ratios=[4.2, 1.3],
                                   hspace=0)
    draw_track(fig.add_subplot(left[0]), track, sample_winners, colors, corners)
    draw_legend(fig.add_subplot(left[1]), colors, legend_labels, note)

    gap_ax = fig.add_subplot(grid[0, 1])
    draw_delta(gap_ax, distance_m, delta, labels, colors)
    trace_axes = [fig.add_subplot(grid[i + 1, 1], sharex=gap_ax) for i in range(len(traces))]
    for ax, (label, (values_a, values_b)) in zip(trace_axes, traces.items()):
        ax.plot(distance_m, values_a, color=colors[0], lw=1.2)
        ax.plot(distance_m, values_b, color=colors[1], lw=1.2)
        ax.set_ylabel(label, color=MUTED, fontsize=9)

    all_axes = [gap_ax] + trace_axes
    for ax in all_axes:
        style_axis(ax)
        for corner in corners:
            ax.axvline(corner["distance"], color=GRID, lw=0.8, ls=":", zorder=0)
        if ax is not all_axes[-1]:
            ax.tick_params(labelbottom=False)
    all_axes[-1].set_xlabel("Distance (m)", color=MUTED, fontsize=9)
    gap_ax.set_xlim(distance_m[0], distance_m[-1])
    label_corners_on_axis(gap_ax, corners)
    mark_key_moments(gap_ax, key_moments, colors)
    write_key_moments(fig, key_moments, colors)

    fig.suptitle(title, color=TEXT, fontsize=14, y=0.97)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.89, bottom=0.2 if key_moments else 0.07)
    return fig


def mark_key_moments(ax, key_moments, colors):
    """Shade each key zone on the gap chart in the gaining driver's colour, numbered."""
    for number, moment in enumerate(key_moments, 1):
        zone, color = moment["zone"], colors[moment["gainer"]]
        ax.axvspan(zone["start"], zone["end"], color=color, alpha=0.12, lw=0, zorder=0)
        # Just below the chart, where the hidden distance labels would be, so the
        # number never sits on top of the gap line.
        ax.text((zone["start"] + zone["end"]) / 2, -0.07, str(number),
                transform=ax.get_xaxis_transform(), color=color, fontsize=12,
                fontweight="bold", ha="center", va="center", clip_on=False)


def write_key_moments(fig, key_moments, colors):
    """Numbered plain-English lines along the bottom of the figure."""
    if not key_moments:
        return
    top = 0.115
    fig.text(0.02, top, "Where the lap was won and lost", color=MUTED, fontsize=10)
    for number, moment in enumerate(key_moments, 1):
        y = top - 0.03 * number
        fig.text(0.02, y, str(number), color=colors[moment["gainer"]], fontsize=11,
                 fontweight="bold")
        fig.text(0.035, y, moment["text"], color=TEXT, fontsize=11)


def draw_track(ax, track, sample_winners, colors, corners):
    points = np.column_stack([track["X"], track["Y"]]).reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    segment_colors = [colors[w] for w in sample_winners[:-1]]

    ax.set_facecolor(BACKGROUND)
    ax.add_collection(LineCollection(segments, colors=segment_colors, linewidths=6,
                                     capstyle="round"))
    for corner in corners:
        angle = np.radians(corner["angle"])
        x = corner["x"] + CORNER_LABEL_OFFSET * np.cos(angle)
        y = corner["y"] + CORNER_LABEL_OFFSET * np.sin(angle)
        ax.text(x, y, corner["label"], color=MUTED, fontsize=8, ha="center", va="center")
    ax.autoscale()
    ax.margins(0.08)
    ax.set_aspect("equal")
    ax.axis("off")


def draw_legend(ax, colors, legend_labels, note=""):
    ax.axis("off")
    handles = [
        Line2D([0], [0], color=color, lw=6, label=label)
        for color, label in zip(colors, legend_labels)
    ]
    ax.legend(handles=handles, loc="upper center" if note else "center",
              facecolor=BACKGROUND, edgecolor="#444",
              labelcolor=TEXT, fontsize=11, title="Faster in mini-sector",
              title_fontsize=9).get_title().set_color(MUTED)
    if note:
        ax.text(0.5, 0.0, note, transform=ax.transAxes, ha="center", va="bottom",
                color=MUTED, fontsize=9, linespacing=1.6)


def draw_delta(ax, distance_m, delta, labels, colors):
    """Gap line, shaded in the colour of whichever driver is ahead."""
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.fill_between(distance_m, delta, 0, where=delta >= 0, color=colors[0], alpha=0.35,
                    interpolate=True, lw=0)
    ax.fill_between(distance_m, delta, 0, where=delta < 0, color=colors[1], alpha=0.35,
                    interpolate=True, lw=0)
    ax.plot(distance_m, delta, color=TEXT, lw=1.3)
    ax.set_ylabel("Gap (s)", color=MUTED, fontsize=9)

    # Keep zero roughly centred so "ahead" and "behind" read clearly.
    limit = max(np.abs(delta).max() * 1.15, 0.05)
    ax.set_ylim(-limit, limit)
    ax.text(0.005, 0.95, f"{labels[0]} ahead", transform=ax.transAxes, color=colors[0],
            fontsize=9, va="top", fontweight="bold")
    ax.text(0.005, 0.05, f"{labels[1]} ahead", transform=ax.transAxes, color=colors[1],
            fontsize=9, va="bottom", fontweight="bold")


def label_corners_on_axis(ax, corners):
    top = ax.secondary_xaxis("top")
    top.set_xticks([c["distance"] for c in corners], [c["label"] for c in corners])
    top.tick_params(colors=MUTED, labelsize=7, length=0)
    top.spines[:].set_visible(False)


def style_axis(ax):
    ax.set_facecolor(BACKGROUND)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=GRID, lw=0.6)
    for spine in ax.spines.values():
        spine.set_visible(False)


def format_lap_time(seconds):
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:06.3f}"
