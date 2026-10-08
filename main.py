"""F1 Deltaline: see where on track one driver was faster than another.

Examples:
    uv run main.py --year 2024 --event Monza --session Q --drivers LEC NOR
    uv run main.py --year 2024 --event Monza --session R --drivers LEC PIA --laps 30 30
    uv run main.py --year 2024 --event Monza --session R --drivers LEC PIA --list-laps
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from f1_deltaline.analysis import (DEFAULT_SECTORS, check_lap_choices, compare_laps, draw,
                                   lap_rows, resolve_drivers, summary_lines)
from f1_deltaline.data import load_session
from f1_deltaline.plot import format_lap_time

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


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
    parser.add_argument("--drivers", nargs="+", required=True, metavar="DRIVER",
                        help="Two driver abbreviations, e.g. VER HAM, or one driver with "
                             "--laps to compare two of their laps, e.g. VER --laps 5 40")
    parser.add_argument("--laps", nargs=2, type=parse_lap_choice, metavar=("LAP_A", "LAP_B"),
                        default=[None, None],
                        help="Lap number for each driver, or 'fastest' (default: both fastest)")
    parser.add_argument("--list-laps", action="store_true",
                        help="List both drivers' laps and exit")
    parser.add_argument("--sectors", type=int, default=DEFAULT_SECTORS,
                        help="Number of mini-sectors")
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
        hint = ", e.g. --laps 5 40 (use --list-laps to see them)" \
            if "Choose two different laps" in str(error) else ""
        raise SystemExit(f"Error: {error}{hint}")

    print(f"Loading {args.year} {event} {args.session} (first load can take a minute)...")
    session = load_session(args.year, event, args.session)

    if args.list_laps:
        for driver in dict.fromkeys(drivers):  # each driver once, in order
            print_laps(session.laps, driver)
        return

    try:
        comparison = compare_laps(session, drivers, args.laps, args.sectors)
    except ValueError as error:
        raise SystemExit(f"Error: {error}")
    for line in summary_lines(comparison):
        print(line)

    fig, _ = draw(comparison)
    OUTPUT_DIR.mkdir(exist_ok=True)
    names = [f"{d}_L{int(lap['LapNumber'])}" for d, lap in zip(drivers, comparison.laps)]
    out = OUTPUT_DIR / f"{args.year}_{session.event['EventName'].replace(' ', '_')}_{args.session}_{names[0]}_vs_{names[1]}.png"
    fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
    print(f"Saved {out}")

    if not args.no_show:
        plt.show()


def print_laps(laps, driver):
    rows = lap_rows(laps, driver)
    if not rows:
        print(f"\n{driver}: no laps in this session")
        return
    print(f"\n{driver}")
    for row in rows:
        time = format_lap_time(row["lap_time"]) if row["lap_time"] is not None else "no time"
        print(f"  {row['description']:<32} {time:>9}   {', '.join(row['notes'])}")


if __name__ == "__main__":
    main()
