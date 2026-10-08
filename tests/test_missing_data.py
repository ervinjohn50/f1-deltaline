"""Sessions with gaps in F1's data, like the 2026 Monaco race, where position data
stops partway through. Fake sessions stand in for the real one."""

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastf1.core import Laps  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

import f1_deltaline.data as data  # noqa: E402
from f1_deltaline.analysis import distance_at_point, point_at  # noqa: E402
from f1_deltaline.plot import draw_track  # noqa: E402
from test_app import make_comparison  # noqa: E402


def test_drivers_without_a_timed_lap_are_left_out():
    class Session:
        laps = Laps(pd.DataFrame({
            "Driver": ["ANT", "HAM", "VER"], "DriverNumber": ["12", "44", "3"],
            "LapTime": pd.to_timedelta([73.5, 74.6, None], unit="s")}))
        results = pd.DataFrame({"Abbreviation": ["ANT", "VER", "HAM"],
                                "Position": [1.0, 2.0, 3.0]})
    assert data.drivers_in_order(Session()) == ["ANT", "HAM"]


def test_track_map_says_unavailable_without_position_data():
    ax = Figure().add_subplot()
    track = pd.DataFrame({"X": [np.nan] * 3, "Y": [np.nan] * 3})
    draw_track(ax, track, np.array([0, 1, 0]), ("red", "blue"), corners=[])
    assert [t.get_text() for t in ax.texts] == ["Track map unavailable:\n"
                                                "no position data for this lap"]


def test_hover_without_position_data():
    c = make_comparison()
    c.tels[0]["X"] = c.tels[0]["Y"] = np.nan
    assert np.isnan(point_at(c, 500)["x"])          # no ring on the map
    assert point_at(c, 500)["speed"] == (200, 210)  # but the charts still read out
    assert distance_at_point(c, 5000, 0) is None


class FakeEvent(dict):
    year = 2026


class FakeSession:
    """A session whose corners can (or can't) be placed."""
    def __init__(self, name, has_corners, loads=None):
        self.name, self.has_corners, self.loads = name, has_corners, loads
        self.event = FakeEvent(RoundNumber=6, Session1="Practice 1", Session2="Practice 2",
                               Session3="Practice 3", Session4="Qualifying", Session5="Race")

    def load(self, **_):
        self.loads.append(self.name)

    def get_circuit_info(self):
        if not self.has_corners:
            raise KeyError("None of ['Date'] are in the columns")  # what FastF1 raises

        class Info:
            corners = pd.DataFrame({"Number": [1], "Letter": [""], "Distance": [150.0],
                                    "X": [10.0], "Y": [20.0], "Angle": [90.0]})
        return Info()


def test_corners_are_borrowed_from_qualifying_when_the_race_has_none(monkeypatch):
    loads = []
    monkeypatch.setattr(data.fastf1, "get_session",
                        lambda year, round_, name: FakeSession(name, True, loads))
    corners = data.corners(FakeSession("Race", has_corners=False))
    assert loads == ["Qualifying"]  # tried first, and it worked
    assert corners == [{"label": "1", "distance": 150.0, "x": 10.0, "y": 20.0, "angle": 90.0}]


def test_corner_fallback_gives_up_after_two_sessions(monkeypatch):
    loads = []
    monkeypatch.setattr(data.fastf1, "get_session",
                        lambda year, round_, name: FakeSession(name, False, loads))
    assert data.corners(FakeSession("Race", has_corners=False)) == []
    assert loads == ["Qualifying", "Practice 3"]  # best sources first, no more than two


def test_corner_lookup_is_remembered_for_the_session(monkeypatch):
    loads = []
    monkeypatch.setattr(data.fastf1, "get_session",
                        lambda year, round_, name: FakeSession(name, True, loads))
    race = FakeSession("Race", has_corners=False)
    first = data.corner_data(race)
    second = data.corner_data(race)  # e.g. pressing Compare again
    assert loads == ["Qualifying"]   # the fallback ran once, not twice
    assert first == second and first[1] == "Qualifying"


def test_corners_from_the_session_itself_are_not_borrowed():
    corners, borrowed_from = data.corner_data(FakeSession("Qualifying", has_corners=True))
    assert len(corners) == 1 and borrowed_from is None


# --- data notes -------------------------------------------------------------------

from f1_deltaline.analysis import data_notes, map_track  # noqa: E402


def lap(seconds=None, x=None):
    """Telemetry for a 1 km lap sampled every 0.25 s unless seconds are given."""
    seconds = np.arange(0, 20.25, 0.25) if seconds is None else np.asarray(seconds, float)
    distance = seconds * 50
    x = distance * 10 if x is None else x
    return pd.DataFrame({"Seconds": seconds, "Distance": distance, "X": x, "Y": 0.0})


def test_no_notes_for_clean_data():
    tels = [lap(), lap()]
    assert data_notes(["LEC", "NOR"], tels, tels[0]) == []


def test_note_for_a_real_car_data_gap_but_not_a_normal_one():
    before = np.arange(0, 10.25, 0.25)  # readings up to 10.0 s
    normal = np.concatenate([before, np.arange(11.1, 20, 0.25)])  # 1.1 s gap: happens
    broken = np.concatenate([before, np.arange(12.5, 20, 0.25)])  # 2.5 s gap: flagged
    notes = data_notes(["LEC", "NOR"], [lap(normal), lap(broken)], lap())
    assert notes == ["NOR's car data has a 2.5s gap near 500 m, "
                     "so the charts are less accurate there."]


def test_notes_for_missing_and_partial_position_data():
    no_position = lap(x=np.nan)
    assert data_notes(["A", "B"], [no_position, no_position], no_position) == [
        "No track map: there's no position data for these laps in this session."]
    partial = lap()
    partial.loc[10:20, "X"] = np.nan
    assert data_notes(["A", "B"], [partial, lap()], partial) == [
        "Part of the track map is missing: there are gaps in the position data."]


def test_note_for_borrowed_corners():
    tels = [lap(), lap()]
    assert data_notes(["A", "B"], tels, tels[0], corners_from="Qualifying") == [
        "Corner positions come from Qualifying, because this session's data can't place them."]


def test_track_map_uses_lap_b_when_only_lap_b_has_position_data():
    a, b = lap(x=np.nan), lap()
    assert map_track([a, b]) is b
    assert map_track([lap(), b]) is not b  # lap A preferred when it has data
    assert map_track([a, a]) is a           # neither: lap A, drawn as "unavailable"


def test_fastf1_warnings_follow_the_chosen_level(monkeypatch):
    levels = []
    monkeypatch.setattr(data.fastf1, "set_log_level", levels.append)
    data.setup_fastf1()
    monkeypatch.setattr(data, "FASTF1_LOG_LEVEL", "ERROR")  # what the desktop app sets
    data.setup_fastf1()
    assert levels == ["WARNING", "ERROR"]  # command line shows warnings, the app doesn't
