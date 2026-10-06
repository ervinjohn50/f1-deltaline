"""F1 Deltaline: see where on track one driver was faster than another.

Example:
    uv run main.py --year 2024 --event Monza --session Q --drivers LEC NOR
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from f1_deltaline.compare import sector_index, sector_times, sector_winners
from f1_deltaline.data import fastest_lap, lap_telemetry, load_session
from f1_deltaline.plot import driver_colors, plot_comparison

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def parse_args():
    parser = argparse.ArgumentParser(description="Compare two drivers' fastest laps.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--event", required=True, help="Event name or round, e.g. Monza or 16")
    parser.add_argument("--session", default="Q", help="R, Q, S, FP1, FP2, FP3 (default Q)")
    parser.add_argument("--drivers", nargs=2, required=True, metavar=("A", "B"),
                        help="Driver abbreviations, e.g. VER HAM")
    parser.add_argument("--sectors", type=int, default=25, help="Number of mini-sectors")
    parser.add_argument("--no-show", action="store_true", help="Save the image without opening a window")
    return parser.parse_args()


def main():
    args = parse_args()
    event = int(args.event) if args.event.isdigit() else args.event
    drivers = [d.upper() for d in args.drivers]

    print(f"Loading {args.year} {event} {args.session} (first load can take a minute)...")
    session = load_session(args.year, event, args.session)

    laps = [fastest_lap(session, d) for d in drivers]
    tels = [lap_telemetry(lap) for lap in laps]
    lap_times = [lap["LapTime"].total_seconds() for lap in laps]

    times = [sector_times(t["Distance"], t["Seconds"], args.sectors) for t in tels]
    winners = sector_winners(times[0], times[1])

    # Draw the track using driver A's line; colour each sample by its sector's winner.
    sample_winners = winners[sector_index(tels[0]["Distance"], args.sectors)]

    won = np.bincount(winners, minlength=2)
    gap = lap_times[1] - lap_times[0]
    print(f"{drivers[0]}: {won[0]} mini-sectors  |  {drivers[1]}: {won[1]} mini-sectors")
    print(f"Lap time gap: {drivers[0]} {'ahead' if gap > 0 else 'behind'} by {abs(gap):.3f}s")

    title = f"{session.event['EventName']} {session.event.year} · {session.name}\n" \
            f"Fastest laps: who was quicker where"
    fig = plot_comparison(tels[0], sample_winners, drivers,
                          driver_colors(session, *drivers), lap_times, title)

    OUTPUT_DIR.mkdir(exist_ok=True)
    out = OUTPUT_DIR / f"{args.year}_{session.event['EventName'].replace(' ', '_')}_{args.session}_{drivers[0]}_vs_{drivers[1]}.png"
    fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
    print(f"Saved {out}")

    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()
