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
                               pick_lap, theoretical_best)
from f1_deltaline.explain import MIN_GAIN_S, explain_lap
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
        raise ValueError(f"both laps would be {drivers[0]}'s {which}. Choose two different "
                         f"laps, e.g. --laps 5 40 (use --list-laps to see them)")


def parse_args():
    parser = argparse.ArgumentParser(description="Compare two drivers' laps.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--event", required=True, help="Event name or round, e.g. Monza or 16")
    parser.add_argument("--session", default="Q", help="R, Q, S, FP1, FP2, FP3 (default Q)")
    parser.add_argument("--drivers", nargs="+", required=True, metavar="DRIVER",
                        help="Two driver abbreviations, e.g. VER HAM, or one driver with "
                             "--laps to compare two of their laps, e.g. VER --laps 5 40")
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
    try:
        drivers = resolve_drivers(args.drivers)
        if not args.list_laps:
            check_lap_choices(drivers, args.laps)
    except ValueError as error:
        raise SystemExit(f"Error: {error}")
    same_driver = drivers[0] == drivers[1]

    print(f"Loading {args.year} {event} {args.session} (first load can take a minute)...")
    session = load_session(args.year, event, args.session)

    if args.list_laps:
        for driver in dict.fromkeys(drivers):  # each driver once, in order
            print_laps(session.laps, driver)
        return

    try:
        laps = [pick_lap(session.laps, d, n) for d, n in zip(drivers, args.laps)]
    except ValueError as error:
        raise SystemExit(f"Error: {error}")
    # e.g. --drivers VER --laps fastest 33 when lap 33 is the fastest
    if same_driver and laps[0]["LapNumber"] == laps[1]["LapNumber"]:
        raise SystemExit(f"Error: both laps are {drivers[0]}'s lap "
                         f"{int(laps[0]['LapNumber'])}. Choose two different laps.")
    tels = [lap_telemetry(lap) for lap in laps]
    lap_times = [lap["LapTime"].total_seconds() for lap in laps]
    descriptions = [describe_lap(lap) for lap in laps]

    for driver, lap, description, lap_time in zip(drivers, laps, descriptions, lap_times):
        print(f"{driver} {description}: {format_lap_time(lap_time)}")
        if is_pit_lap(lap):
            print(f"  Note: this is an in-lap or out-lap, so part of it is in the pit lane "
                  f"and the comparison may be misleading.")

    # Name each lap by driver, adding the lap number when laps were chosen by hand
    # (always the case for one driver, since that's the only way to tell the laps apart).
    chose_laps = any(n is not None for n in args.laps)
    labels = [f"{d} L{int(lap['LapNumber'])}" if chose_laps or same_driver else d
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
    sectors = [f"{n} mini-sector{'s' if n != 1 else ''}" for n in won]
    print(f"{labels[0]}: {sectors[0]}  |  {labels[1]}: {sectors[1]}")
    print(f"Lap time gap: {labels[0]} {'ahead' if gap > 0 else 'behind'} by {abs(gap):.3f}s")

    printed, note_lines = theoretical_best_summary(session.laps, drivers)
    print()
    for line in printed:
        print(line)
    if session.name in ("Race", "Sprint"):
        print("  Note: in a race the best sectors can come from very different fuel loads "
              "and tyres, so treat this as rough.")

    corner_list = corners(session)
    key_moments = explain_lap(distance_m, delta, traces, corner_list, labels)
    print("\nWhere the lap was won and lost:")
    if key_moments:
        for moment in key_moments:
            print(f"  {moment['text']}")
    elif not corner_list:
        print("  Not available: no corner data for this track.")
    else:
        print(f"  No single part of the lap changed the gap by {MIN_GAIN_S}s or more.")

    which = f"{labels[0]} vs {labels[1]}" if chose_laps else \
        f"{drivers[0]} vs {drivers[1]}, fastest laps"
    title = f"{session.event['EventName']} {session.event.year} · {session.name} · {which}"
    fig = plot_comparison(tels[0], sample_winners, distance_m, delta, traces, labels,
                          driver_colors(session, *drivers), legend_labels, title,
                          corner_list, note="\n".join(note_lines), key_moments=key_moments)

    OUTPUT_DIR.mkdir(exist_ok=True)
    names = [f"{d}_L{int(lap['LapNumber'])}" for d, lap in zip(drivers, laps)]
    out = OUTPUT_DIR / f"{args.year}_{session.event['EventName'].replace(' ', '_')}_{args.session}_{names[0]}_vs_{names[1]}.png"
    fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
    print(f"Saved {out}")

    if not args.no_show:
        plt.show()


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
        if "Deleted" in lap and lap["Deleted"] == True:  # noqa: E712 (None = unknown)
            notes.append("deleted (track limits)")
        print(f"  {describe_lap(lap):<32} {time:>9}   {', '.join(notes)}")


if __name__ == "__main__":
    main()
