"""Loading sessions and laps from FastF1."""

from pathlib import Path

import fastf1

CACHE_DIR = Path(__file__).resolve().parent.parent / ".fastf1-cache"


def load_session(year, event, session_type):
    CACHE_DIR.mkdir(exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE_DIR))
    session = fastf1.get_session(year, event, session_type)
    session.load(laps=True, telemetry=True, weather=False, messages=False)
    return session


def fastest_lap(session, driver):
    lap = session.laps.pick_drivers(driver).pick_fastest()
    if lap is None or lap.empty:
        raise ValueError(f"No timed lap found for {driver}")
    return lap


def lap_telemetry(lap):
    """Distance, X/Y position and lap time in seconds for one lap."""
    tel = lap.get_telemetry()
    tel["Seconds"] = tel["Time"].dt.total_seconds()
    return tel[["Distance", "X", "Y", "Seconds"]].dropna()
