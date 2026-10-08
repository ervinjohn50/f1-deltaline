"""Loading sessions and laps from FastF1."""

from pathlib import Path

import fastf1
import numpy as np
import pandas as pd

from f1_deltaline.compare import integrate_distance

CACHE_DIR = Path(__file__).resolve().parent.parent / ".fastf1-cache"


# FastF1 prints warnings about problems in F1's data. The command line shows them;
# the desktop app sets this to "ERROR" and reports what matters in its status bar.
FASTF1_LOG_LEVEL = "WARNING"


def setup_fastf1():
    fastf1.set_log_level(FASTF1_LOG_LEVEL)
    CACHE_DIR.mkdir(exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE_DIR))


def load_session(year, event, session_type):
    setup_fastf1()
    session = fastf1.get_session(year, event, session_type)
    # Race control messages are needed to know which laps were deleted (track limits).
    session.load(laps=True, telemetry=True, weather=False, messages=True)
    return session


def load_schedule(year):
    """A season's events, each with the sessions that have already happened."""
    setup_fastf1()
    schedule = fastf1.get_event_schedule(year, include_testing=False)
    return events_with_past_sessions(schedule, pd.Timestamp.now(tz="UTC").tz_localize(None))


def events_with_past_sessions(schedule, now):
    """[{"round": 16, "name": "Italian Grand Prix", "sessions": ["Practice 1", ...]}].

    Only sessions that started before `now` (UTC) are listed, since later ones
    have no data yet; events with none are left out.
    """
    events = []
    for _, event in schedule.iterrows():
        sessions = [event[f"Session{i}"] for i in range(1, 6)
                    if isinstance(event[f"Session{i}"], str) and event[f"Session{i}"]
                    and pd.notna(event[f"Session{i}DateUtc"])
                    and event[f"Session{i}DateUtc"] <= now]
        if sessions:
            events.append({"round": int(event["RoundNumber"]), "name": event["EventName"],
                           "sessions": sessions})
    return events


def drivers_in_order(session):
    """Driver codes with at least one timed lap, in finishing order where known.

    Practice sessions have no finishing order, so drivers are ordered by
    fastest lap instead. Drivers with no timed lap (e.g. out on lap 1) are left
    out, since there's nothing of theirs to compare.
    """
    fastest = session.laps.groupby("Driver")["LapTime"].min().dropna().sort_values()
    results = session.results
    if results is not None and not results.empty and results["Position"].notna().any():
        ordered = results.sort_values("Position", na_position="last")["Abbreviation"]
        return [d for d in ordered if d in fastest.index]
    return list(fastest.index)


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


def theoretical_best(laps, driver):
    """A driver's best sector 1, 2 and 3 from any laps, added up.

    Returns {"total": seconds, "sectors": [(seconds, lap_number), ...]}, or None
    if any sector has no time. Deleted laps (track limits) are left out.
    """
    driver_laps = laps.pick_drivers(driver)
    if "Deleted" in driver_laps:
        driver_laps = driver_laps[driver_laps["Deleted"] != True]  # noqa: E712 (None = unknown)
    sectors = []
    for column in ("Sector1Time", "Sector2Time", "Sector3Time"):
        times = driver_laps[column].dropna()
        if times.empty:
            return None
        best = times.idxmin()
        sectors.append((times[best].total_seconds(), int(driver_laps.loc[best, "LapNumber"])))
    return {"total": sum(seconds for seconds, _ in sectors), "sectors": sectors}


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
    """Distance, X/Y position, driver inputs and lap time in seconds for one lap.

    Some sessions have gaps in their position data (where the car is on track),
    e.g. the 2026 Monaco race, where it stops partway through. Those laps are
    built from car data alone, with X and Y left empty (NaN). Everything except
    the track map still works, because distance comes from speed, not position.
    """
    name = f"{lap['Driver']} lap {int(lap['LapNumber'])}"
    if lap.get_car_data().empty:
        raise ValueError(f"There's no car data (speed, throttle, brake) for {name} in this "
                         f"session, so it can't be compared. Try another lap.")
    if lap.get_pos_data().empty:
        car = lap.get_car_data(pad=1, pad_side="both")
        tel = car.slice_by_lap(lap, interpolate_edges=True)
        tel["X"] = tel["Y"] = np.nan
    else:
        tel = lap.get_telemetry()
    tel["Seconds"] = tel["Time"].dt.total_seconds()
    tel["Brake"] = tel["Brake"].astype(float)
    # Only rows missing car data are dropped; missing position just leaves X/Y empty.
    tel = tel[["X", "Y", "Seconds", "Speed", "Throttle", "Brake"]].dropna(
        subset=["Seconds", "Speed", "Throttle", "Brake"])
    # Replace FastF1's Distance with a more accurate one; see integrate_distance.
    tel["Distance"] = integrate_distance(tel["Speed"], tel["Seconds"])
    return tel


# Sessions to borrow corner positions from, best first (qualifying laps are clean).
CORNER_SOURCES = ["Qualifying", "Sprint Qualifying", "Sprint Shootout", "Race", "Sprint",
                  "Practice 3", "Practice 2", "Practice 1"]


def circuit_info(session):
    try:
        return session.get_circuit_info()
    except Exception:  # e.g. the session has no position data to place the corners
        return None


def corners(session, max_fallbacks=2):
    """Corner labels with their track distance and position, or [] if unavailable."""
    return corner_data(session, max_fallbacks)[0]


def corner_data(session, max_fallbacks=2):
    """(corners, borrowed_from): the corners, and the session they came from if not this one.

    FastF1 places corners along the lap using the session's fastest lap, which
    needs position data. If this session is missing it (e.g. the 2026 Monaco
    race), the corners are taken from another session of the same event, since
    the track is the same all weekend. At most max_fallbacks sessions are tried,
    and each may need downloading the first time.

    The result is remembered on the session, so comparing more laps from it
    doesn't repeat the work.
    """
    cached = getattr(session, "_f1_deltaline_corners", None)
    if cached is None:
        cached = _find_corners(session, max_fallbacks)
        session._f1_deltaline_corners = cached
    return cached


def _find_corners(session, max_fallbacks):
    info, borrowed_from = circuit_info(session), None
    if info is None:
        event = session.event
        others = [event.get(f"Session{i}") for i in range(1, 6)]
        others = [name for name in CORNER_SOURCES if name in others and name != session.name]
        for name in others[:max_fallbacks]:
            try:
                other = fastf1.get_session(event.year, int(event["RoundNumber"]), name)
                other.load(laps=True, telemetry=True, weather=False, messages=False)
            except Exception:
                continue
            info = circuit_info(other)
            if info is not None:
                borrowed_from = name
                break
    if info is None:
        return [], None
    return [
        {"label": f"{int(c.Number)}{c.Letter if isinstance(c.Letter, str) else ''}",
         "distance": c.Distance,
         "x": c.X, "y": c.Y, "angle": c.Angle}
        for c in info.corners.itertuples()
    ], borrowed_from
