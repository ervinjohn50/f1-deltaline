"""Loading sessions and laps from FastF1."""

from pathlib import Path

import fastf1
import pandas as pd

from f1_deltaline.compare import integrate_distance

CACHE_DIR = Path(__file__).resolve().parent.parent / ".fastf1-cache"


def load_session(year, event, session_type):
    fastf1.set_log_level("WARNING")
    CACHE_DIR.mkdir(exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE_DIR))
    session = fastf1.get_session(year, event, session_type)
    session.load(laps=True, telemetry=True, weather=False, messages=False)
    return session


def pick_lap(laps, driver, lap_number=None):
    """A driver's lap by number, or their fastest lap when lap_number is None."""
    driver_laps = laps.pick_drivers(driver)
    if driver_laps.empty:
        raise ValueError(f"No laps found for {driver} in this session")

    if lap_number is None:
        lap = driver_laps.pick_fastest()
        if lap is None or lap.empty:
            raise ValueError(f"No timed lap found for {driver}")
        return lap

    chosen = driver_laps.pick_laps(lap_number)
    if chosen.empty:
        numbers = driver_laps["LapNumber"]
        raise ValueError(f"{driver} has no lap {lap_number} "
                         f"(laps {int(numbers.min())}-{int(numbers.max())})")
    lap = chosen.iloc[0]
    if pd.isna(lap["LapTime"]):
        raise ValueError(f"{driver} lap {lap_number} has no lap time (usually an out lap "
                         f"or an unfinished lap). Use --list-laps to see timed laps.")
    return lap


def is_pit_lap(lap):
    """True for in-laps and out-laps, which start or end in the pit lane."""
    return pd.notna(lap["PitInTime"]) or pd.notna(lap["PitOutTime"])


def describe_lap(lap):
    """Short description such as 'lap 24, Soft, 2 laps old'."""
    parts = [f"lap {int(lap['LapNumber'])}"]
    if isinstance(lap["Compound"], str) and lap["Compound"]:
        tyre = lap["Compound"].title()
        if pd.notna(lap["TyreLife"]):
            age = int(lap["TyreLife"])
            tyre += f", {age} lap{'s' if age != 1 else ''} old"
        parts.append(tyre)
    return ", ".join(parts)


def lap_telemetry(lap):
    """Distance, X/Y position, driver inputs and lap time in seconds for one lap."""
    tel = lap.get_telemetry()
    tel["Seconds"] = tel["Time"].dt.total_seconds()
    tel["Brake"] = tel["Brake"].astype(float)
    tel = tel[["X", "Y", "Seconds", "Speed", "Throttle", "Brake"]].dropna()
    # Replace FastF1's Distance with a more accurate one; see integrate_distance.
    tel["Distance"] = integrate_distance(tel["Speed"], tel["Seconds"])
    return tel


def corners(session):
    """Corner labels with their track distance and position, or [] if unavailable."""
    try:
        info = session.get_circuit_info()
    except Exception:
        return []
    if info is None:
        return []
    return [
        {"label": f"{int(c.Number)}{c.Letter if isinstance(c.Letter, str) else ''}",
         "distance": c.Distance,
         "x": c.X, "y": c.Y, "angle": c.Angle}
        for c in info.corners.itertuples()
    ]
