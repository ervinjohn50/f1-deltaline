"""A full lap comparison, shared by the command line (main.py) and the desktop app."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from f1_deltaline.compare import (lap_fraction, resample, sector_index, sector_times,
                                  sector_winners, time_delta)
from f1_deltaline.data import (corner_data, describe_lap, is_pit_lap, lap_telemetry, pick_lap,
                               theoretical_best)
from f1_deltaline.explain import MIN_GAIN_S, explain_lap
from f1_deltaline.plot import driver_colors, format_lap_time, plot_comparison

GRID_POINTS = 1000  # points along the lap for the gap and input traces
DEFAULT_SECTORS = 25
TRACES = [("Speed (km/h)", "Speed"), ("Throttle (%)", "Throttle"), ("Brake", "Brake")]
# Car data normally arrives every quarter second or so, with the odd gap of up to
# about 1.1s even on clean laps. Longer than this and the charts are noticeably
# less accurate there (at 300 km/h, 2s is about 170 m with no readings).
MAX_CAR_DATA_GAP_S = 2.0


@dataclass
class Comparison:
    """Everything worked out for one comparison, ready to print or draw."""
    session: object
    drivers: list          # e.g. ["LEC", "NOR"], or ["LEC", "LEC"] for one driver
    laps: list             # the two FastF1 laps
    labels: list           # short names, e.g. ["LEC", "NOR"] or ["LEC L14", "LEC L17"]
    legend_labels: list
    descriptions: list     # e.g. "lap 20, Soft, 2 laps old"
    lap_times: list        # seconds
    tels: list             # telemetry for each lap
    track: object          # telemetry used for the track map: lap A's, or lap B's if A
                           # has no position data
    winners: np.ndarray    # 0/1 per mini-sector
    sample_winners: np.ndarray
    distance_m: np.ndarray  # shared x-axis for the gap and traces
    delta: np.ndarray       # running gap, positive = driver A ahead
    traces: dict
    corners: list
    key_moments: list
    best_lines: list       # theoretical best, for the terminal
    best_notes: list       # theoretical best, short, for the image
    data_notes: list       # gaps in F1's data that affect this comparison
    title: str

    @property
    def gap(self):
        """Lap time difference in seconds; positive means driver A was faster."""
        return self.lap_times[1] - self.lap_times[0]


def resolve_drivers(names):
    """Two driver codes from one or two given; one driver means compare two of their laps."""
    if len(names) not in (1, 2):
        raise ValueError(f"expected one or two drivers, got {len(names)}")
    drivers = [name.upper() for name in names]
    return drivers * 2 if len(drivers) == 1 else drivers


def check_lap_choices(drivers, lap_choices):
    """Catch comparing a lap with itself before any data is loaded."""
    if drivers[0] != drivers[1]:
        return
    if lap_choices[0] == lap_choices[1]:
        which = "fastest lap" if lap_choices[0] is None else f"lap {lap_choices[0]}"
        raise ValueError(f"both laps would be {drivers[0]}'s {which}. Choose two different laps")


def compare_laps(session, drivers, lap_choices=(None, None), n_sectors=DEFAULT_SECTORS):
    """Compare two laps from a loaded session. Raises ValueError for laps that can't be used.

    lap_choices: a lap number for each driver, or None for their fastest lap.
    """
    same_driver = drivers[0] == drivers[1]
    laps = [pick_lap(session.laps, d, n) for d, n in zip(drivers, lap_choices)]
    # e.g. one driver with laps "fastest" and 33, when lap 33 is the fastest
    if same_driver and laps[0]["LapNumber"] == laps[1]["LapNumber"]:
        raise ValueError(f"both laps are {drivers[0]}'s lap {int(laps[0]['LapNumber'])}. "
                         f"Choose two different laps.")
    tels = [lap_telemetry(lap) for lap in laps]
    lap_times = [lap["LapTime"].total_seconds() for lap in laps]
    descriptions = [describe_lap(lap) for lap in laps]

    # Name each lap by driver, adding the lap number when laps were chosen by hand
    # (always the case for one driver, since that's the only way to tell the laps apart).
    chose_laps = any(n is not None for n in lap_choices)
    labels = [f"{d} L{int(lap['LapNumber'])}" if chose_laps or same_driver else d
              for d, lap in zip(drivers, laps)]
    legend_labels = [f"{d}  {format_lap_time(t)}  ({desc})"
                     for d, t, desc in zip(drivers, lap_times, descriptions)]

    times = [sector_times(t["Distance"], t["Seconds"], n_sectors) for t in tels]
    winners = sector_winners(times[0], times[1])
    # Colour each sample on the track map by its mini-sector's winner.
    track = map_track(tels)
    sample_winners = winners[sector_index(track["Distance"], n_sectors)]

    # Shared grid along the lap, in metres of driver A's lap, for the gap and traces.
    grid = np.linspace(0.0, 1.0, GRID_POINTS)
    lap_length = tels[0]["Distance"].iloc[-1] - tels[0]["Distance"].iloc[0]
    distance_m = grid * lap_length
    delta = time_delta(tels[0]["Distance"], tels[0]["Seconds"],
                       tels[1]["Distance"], tels[1]["Seconds"], grid)
    traces = {label: tuple(resample(t["Distance"], t[column], grid) for t in tels)
              for label, column in TRACES}

    corner_list, corners_from = corner_data(session)
    best_lines, best_notes = theoretical_best_summary(session.laps, drivers)
    which = f"{labels[0]} vs {labels[1]}" if chose_laps else \
        f"{drivers[0]} vs {drivers[1]}, fastest laps"

    return Comparison(
        session=session, drivers=drivers, laps=laps, labels=labels,
        legend_labels=legend_labels, descriptions=descriptions, lap_times=lap_times,
        tels=tels, track=track, winners=winners, sample_winners=sample_winners,
        distance_m=distance_m,
        delta=delta, traces=traces, corners=corner_list,
        key_moments=explain_lap(distance_m, delta, traces, corner_list, labels),
        best_lines=best_lines, best_notes=best_notes,
        data_notes=data_notes(labels, tels, track, corners_from),
        title=f"{session.event['EventName']} {session.event.year} · {session.name} · {which}",
    )


def map_track(tels):
    """Telemetry to draw the track map from: lap A's line, or lap B's if only B has
    position data (lap A's, with no map, if neither does)."""
    return next((t for t in tels if t["X"].notna().any()), tels[0])


def data_notes(labels, tels, track, corners_from=None):
    """Plain-English notes on gaps in F1's data that affect a comparison."""
    notes = []
    missing = track["X"].isna()
    if missing.all():
        notes.append("No track map: there's no position data for these laps in this session.")
    elif missing.any():
        notes.append("Part of the track map is missing: there are gaps in the position data.")
    for label, tel in zip(labels, tels):
        steps = np.diff(tel["Seconds"].to_numpy())
        if steps.size and steps.max() > MAX_CAR_DATA_GAP_S:
            at = tel["Distance"].iloc[int(np.argmax(steps))]
            notes.append(f"{label}'s car data has a {steps.max():.1f}s gap near {at:,.0f} m, "
                         f"so the charts are less accurate there.")
    if corners_from:
        notes.append(f"Corner positions come from {corners_from}, because this session's "
                     f"data can't place them.")
    return notes


def summary_lines(c):
    """The text summary of a comparison, one line per item."""
    lines = []
    for driver, lap, description, lap_time in zip(c.drivers, c.laps, c.descriptions,
                                                  c.lap_times):
        lines.append(f"{driver} {description}: {format_lap_time(lap_time)}")
        if is_pit_lap(lap):
            lines.append("  Note: this is an in-lap or out-lap, so part of it is in the pit "
                         "lane and the comparison may be misleading.")

    won = np.bincount(c.winners, minlength=2)
    sectors = [f"{n} mini-sector{'s' if n != 1 else ''}" for n in won]
    lines.append(f"{c.labels[0]}: {sectors[0]}  |  {c.labels[1]}: {sectors[1]}")
    lines.append(f"Lap time gap: {c.labels[0]} {'ahead' if c.gap > 0 else 'behind'} "
                 f"by {abs(c.gap):.3f}s")

    lines += ["", *c.best_lines]
    if c.session.name in ("Race", "Sprint"):
        lines.append("  Note: in a race the best sectors can come from very different fuel "
                     "loads and tyres, so treat this as rough.")

    lines += ["", "Where the lap was won and lost:"]
    if c.key_moments:
        lines += [f"  {moment['text']}" for moment in c.key_moments]
    elif not c.corners:
        lines.append("  Not available: corner positions couldn't be found for this event.")
    else:
        lines.append(f"  No single part of the lap changed the gap by {MIN_GAIN_S}s or more.")
    if c.data_notes:
        lines += ["", "Data notes:", *(f"  {note}" for note in c.data_notes)]
    return lines


def point_at(c, distance):
    """Both laps at one distance along the lap, for the app's hover readout.

    Returns the track position (on driver A's line), each driver's speed and
    throttle, and the gap (positive = driver A ahead).
    """
    distance = float(np.clip(distance, c.distance_m[0], c.distance_m[-1]))
    track = c.track
    fraction = lap_fraction(track["Distance"])
    at = distance / c.distance_m[-1]
    return {
        "distance": distance,
        "x": float(np.interp(at, fraction, track["X"])),
        "y": float(np.interp(at, fraction, track["Y"])),
        "speed": tuple(float(np.interp(distance, c.distance_m, v))
                       for v in c.traces["Speed (km/h)"]),
        "throttle": tuple(float(np.interp(distance, c.distance_m, v))
                          for v in c.traces["Throttle (%)"]),
        "gap": float(np.interp(distance, c.distance_m, c.delta)),
    }


def distance_at_point(c, x, y, max_offset=1000):
    """Distance along the lap nearest a point on the track map, or None if the point
    is more than max_offset track units (1/10 m, so 100 m) from the racing line."""
    track = c.track
    offsets = np.hypot(track["X"].to_numpy() - x, track["Y"].to_numpy() - y)
    if np.isnan(offsets).all():  # no position data for this lap
        return None
    nearest = int(np.nanargmin(offsets))
    if offsets[nearest] > max_offset:
        return None
    return float(lap_fraction(track["Distance"])[nearest] * c.distance_m[-1])


def hover_text(c, point):
    """One-line readout for the app's status bar."""
    a, b = c.labels
    gap = point["gap"]
    leader = a if gap > 0 else b
    return (f"{point['distance']:,.0f} m   ·   "
            f"{a}: {point['speed'][0]:.0f} km/h, {point['throttle'][0]:.0f}% throttle   ·   "
            f"{b}: {point['speed'][1]:.0f} km/h, {point['throttle'][1]:.0f}% throttle   ·   "
            f"{leader} ahead by {abs(gap):.3f}s")


def draw(c, fig=None):
    """Draw the comparison figure, into fig if given. Returns (fig, axes)."""
    return plot_comparison(c.track, c.sample_winners, c.distance_m, c.delta, c.traces,
                           c.labels, driver_colors(c.session, *c.drivers), c.legend_labels,
                           c.title, c.corners, note="\n".join(c.best_notes),
                           key_moments=c.key_moments, fig=fig)


def theoretical_best_summary(laps, drivers):
    """Lines for the terminal and short lines for the image, one per driver."""
    printed, notes = [], []
    for driver in dict.fromkeys(drivers):  # each driver once
        best = theoretical_best(laps, driver)
        if best is None:
            printed.append(f"{driver} theoretical best: not available (missing sector times)")
            continue
        fastest = pick_lap(laps, driver)
        best_time = format_lap_time(best["total"])
        from_laps = ", ".join(f"S{i} lap {lap}" for i, (_, lap) in enumerate(best["sectors"], 1))
        if all(lap == fastest["LapNumber"] for _, lap in best["sectors"]):
            result = "all three best sectors on their fastest lap"
        else:
            left = fastest["LapTime"].total_seconds() - best["total"]
            result = f"{left:.3f}s quicker than their fastest lap"
        printed.append(f"{driver} theoretical best: {best_time} ({from_laps}), {result}")
        notes.append(f"{driver} theoretical best {best_time}: {result}")
    return printed, notes


def lap_rows(laps, driver):
    """Each of a driver's laps as a dict, for listing or choosing laps.

    Keys: number, lap_time (seconds or None), description, notes (list of strings).
    """
    driver_laps = laps.pick_drivers(driver)
    if driver_laps.empty:
        return []
    fastest = driver_laps.pick_fastest()
    fastest_number = fastest["LapNumber"] if fastest is not None and not fastest.empty else None
    rows = []
    for _, lap in driver_laps.iterlaps():
        notes = []
        if pd.notna(lap["PitOutTime"]):
            notes.append("out-lap")
        if pd.notna(lap["PitInTime"]):
            notes.append("in-lap")
        if lap["LapNumber"] == fastest_number:
            notes.append("fastest")
        if "Deleted" in lap and lap["Deleted"] == True:  # noqa: E712 (None = unknown)
            notes.append("deleted (track limits)")
        rows.append({
            "number": int(lap["LapNumber"]),
            "lap_time": lap["LapTime"].total_seconds() if pd.notna(lap["LapTime"]) else None,
            "description": describe_lap(lap),
            "notes": notes,
        })
    return rows
