"""Loading sessions and laps from FastF1."""

from pathlib import Path

import fastf1

from f1_deltaline.compare import integrate_distance

CACHE_DIR = Path(__file__).resolve().parent.parent / ".fastf1-cache"


def load_session(year, event, session_type):
    fastf1.set_log_level("WARNING")
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
