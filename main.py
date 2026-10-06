"""F1 Deltaline: see where on track one driver was faster than another.

Examples:
    uv run main.py --year 2024 --event Monza --session Q --drivers LEC NOR
    uv run main.py --year 2024 --event Monza --session R --drivers LEC PIA --laps 30 30
    uv run main.py --year 2024 --event Monza --session R --drivers LEC PIA --list-laps
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from f1_deltaline.compare import (resample, sector_index, sector_times, sector_winners,
                                  time_delta)
from f1_deltaline.data import (corners, describe_lap, is_pit_lap, lap_telemetry, load_session,
                               pick_lap)
from f1_deltaline.plot import driver_colors, format_lap_time, plot_comparison

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
GRID_POINTS = 1000  # points along the lap for the gap and input traces


def parse_lap_choice(value):
    """A lap number, or None for 'fastest'."""
    if value.lower() in ("fastest", "f"):
        return None
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError(f"expected a lap number or 'fastest', got '{value}'")
    return int(value)


def parse_args():
    parser = argparse.ArgumentParser(description="Compare two drivers' laps.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--event", required=True, help="Event name or round, e.g. Monza or 16")
    parser.add_argument("--session", default="Q", help="R, Q, S, FP1, FP2, FP3 (default Q)")
    parser.add_argument("--drivers", nargs=2, required=True, metavar=("A", "B"),
                        help="Driver abbreviations, e.g. VER HAM")
    parser.add_argument("--laps", nargs=2, type=parse_lap_choice, metavar=("LAP_A", "LAP_B"),
                        default=[None, None],
                        help="Lap number for each driver, or 'fastest' (default: both fastest)")
    parser.add_argument("--list-laps", action="store_true",
                        help="List both drivers' laps and exit")
    parser.add_argument("--sectors", type=int, default=25, help="Number of mini-sectors")
    parser.add_argument("--no-show", action="store_true", help="Save the image without opening a window")
    return parser.parse_args()


def main():
    args = parse_args()
    event = int(args.event) if args.event.isdigit() else args.event
    drivers = [d.upper() for d in args.drivers]

    print(f"Loading {args.year} {event} {args.session} (first load can take a minute)...")
    session = load_session(args.year, event, args.session)

    if args.list_laps:
        for driver in drivers:
            print_laps(session.laps, driver)
        return

    try:
        laps = [pick_lap(session.laps, d, n) for d, n in zip(drivers, args.laps)]
    except ValueError as error:
        raise SystemExit(f"Error: {error}")
    tels = [lap_telemetry(lap) for lap in laps]
    lap_times = [lap["LapTime"].total_seconds() for lap in laps]
    descriptions = [describe_lap(lap) for lap in laps]

    for driver, lap, description, lap_time in zip(drivers, laps, descriptions, lap_times):
        print(f"{driver} {description}: {format_lap_time(lap_time)}")
        if is_pit_lap(lap):
            print(f"  Note: this is an in-lap or out-lap, so part of it is in the pit lane "
                  f"and the comparison may be misleading.")

    # Name each lap by driver, adding the lap number when laps were chosen by hand.
    chose_laps = any(n is not None for n in args.laps)
    labels = [f"{d} L{int(lap['LapNumber'])}" if chose_laps else d
              for d, lap in zip(drivers, laps)]
    legend_labels = [f"{d}  {format_lap_time(t)}  ({desc})"
                     for d, t, desc in zip(drivers, lap_times, descriptions)]

    times = [sector_times(t["Distance"], t["Seconds"], args.sectors) for t in tels]
    winners = sector_winners(times[0], times[1])

    # Draw the track using driver A's line; colour each sample by its sector's winner.
    sample_winners = winners[sector_index(tels[0]["Distance"], args.sectors)]

    # Shared grid along the lap, in metres of driver A's lap, for the gap and traces.
    grid = np.linspace(0.0, 1.0, GRID_POINTS)
    lap_length = tels[0]["Distance"].iloc[-1] - tels[0]["Distance"].iloc[0]
    distance_m = grid * lap_length
    delta = time_delta(tels[0]["Distance"], tels[0]["Seconds"],
                       tels[1]["Distance"], tels[1]["Seconds"], grid)
    traces = {
        label: tuple(resample(t["Distance"], t[column], grid) for t in tels)
        for label, column in [("Speed (km/h)", "Speed"), ("Throttle (%)", "Throttle"),
                              ("Brake", "Brake")]
    }

    won = np.bincount(winners, minlength=2)
    gap = lap_times[1] - lap_times[0]
    print(f"{labels[0]}: {won[0]} mini-sectors  |  {labels[1]}: {won[1]} mini-sectors")
    print(f"Lap time gap: {labels[0]} {'ahead' if gap > 0 else 'behind'} by {abs(gap):.3f}s")

    which = f"{labels[0]} vs {labels[1]}" if chose_laps else \
        f"{drivers[0]} vs {drivers[1]}, fastest laps"
    title = f"{session.event['EventName']} {session.event.year} · {session.name} · {which}"
    fig = plot_comparison(tels[0], sample_winners, distance_m, delta, traces, labels,
                          driver_colors(session, *drivers), legend_labels, title,
                          corners(session))

    OUTPUT_DIR.mkdir(exist_ok=True)
    names = [f"{d}_L{int(lap['LapNumber'])}" for d, lap in zip(drivers, laps)]
    out = OUTPUT_DIR / f"{args.year}_{session.event['EventName'].replace(' ', '_')}_{args.session}_{names[0]}_vs_{names[1]}.png"
    fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
    print(f"Saved {out}")

    if not args.no_show:
        plt.show()


def print_laps(laps, driver):
    driver_laps = laps.pick_drivers(driver)
    if driver_laps.empty:
        print(f"\n{driver}: no laps in this session")
        return
    fastest = driver_laps.pick_fastest()
    fastest_number = fastest["LapNumber"] if fastest is not None and not fastest.empty else None
    print(f"\n{driver}")
    for _, lap in driver_laps.iterlaps():
        time = format_lap_time(lap["LapTime"].total_seconds()) if pd.notna(lap["LapTime"]) \
            else "no time"
        notes = []
        if pd.notna(lap["PitOutTime"]):
            notes.append("out-lap")
        if pd.notna(lap["PitInTime"]):
            notes.append("in-lap")
        if lap["LapNumber"] == fastest_number:
            notes.append("fastest")
        print(f"  {describe_lap(lap):<32} {time:>9}   {', '.join(notes)}")


if __name__ == "__main__":
    main()
