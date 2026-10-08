"""Tests for the desktop app and the helpers behind it. No race data is downloaded:
the window is given fake loaders, and the hover maths uses a made-up lap."""

import numpy as np
import pandas as pd
import pytest
from fastf1.core import Laps

import f1_deltaline.app as app_module
from f1_deltaline.analysis import Comparison, distance_at_point, hover_text, point_at
from f1_deltaline.app import MainWindow, lap_choice_label
from f1_deltaline.data import drivers_in_order, events_with_past_sessions

# --- schedule and drivers -------------------------------------------------------


def make_schedule():
    names = ["Practice 1", "Practice 2", "Practice 3", "Qualifying", "Race"]
    rows = []
    for round_, name, first_day in [(1, "Bahrain Grand Prix", "2024-02-29"),
                                    (2, "Saudi Arabian Grand Prix", "2024-03-07"),
                                    (3, "Australian Grand Prix", "2024-03-22")]:
        row = {"RoundNumber": round_, "EventName": name}
        dates = pd.date_range(f"{first_day} 12:00", periods=len(names), freq="12h")
        for i, (session, when) in enumerate(zip(names, dates), 1):
            row[f"Session{i}"] = session
            row[f"Session{i}DateUtc"] = when
        rows.append(row)
    return pd.DataFrame(rows)


def test_events_only_list_sessions_that_have_happened():
    # Saudi Practice 2 was at 00:00 on 8 March and Practice 3 at 12:00.
    events = events_with_past_sessions(make_schedule(), now=pd.Timestamp("2024-03-08 06:00"))
    assert events == [
        {"round": 1, "name": "Bahrain Grand Prix",
         "sessions": ["Practice 1", "Practice 2", "Practice 3", "Qualifying", "Race"]},
        {"round": 2, "name": "Saudi Arabian Grand Prix",
         "sessions": ["Practice 1", "Practice 2"]},
    ]  # Australia hasn't started, so it's left out


class FakeSession:
    def __init__(self, positions=(1.0, 2.0)):
        seconds = lambda values: pd.to_timedelta(values, unit="s")  # noqa: E731
        self.laps = Laps(pd.DataFrame({
            "Driver": ["NOR", "NOR", "NOR", "PIA", "PIA", "PIA"],
            "DriverNumber": ["4", "4", "4", "81", "81", "81"],
            "LapNumber": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
            "LapTime": seconds([None, 79.3, 95.0, None, 79.6, 79.4]),
            "Compound": ["SOFT"] * 6,
            "TyreLife": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
            "PitOutTime": seconds([600, None, None, 610, None, None]),
            "PitInTime": seconds([None, None, 900, None, None, None]),
            "IsPersonalBest": [False, True, False, False, True, True],
            "Deleted": [False] * 6,
        }))
        self.results = pd.DataFrame({"Abbreviation": ["PIA", "NOR"],
                                     "Position": [positions[1], positions[0]]})


def test_drivers_in_order_follows_the_result():
    assert drivers_in_order(FakeSession(positions=(1.0, 2.0))) == ["NOR", "PIA"]
    assert drivers_in_order(FakeSession(positions=(2.0, 1.0))) == ["PIA", "NOR"]


def test_drivers_in_order_uses_fastest_lap_when_there_is_no_result():
    # Practice: no positions, so order by fastest lap (NOR 1:19.3 beats PIA 1:19.4).
    assert drivers_in_order(FakeSession(positions=(np.nan, np.nan))) == ["NOR", "PIA"]


def test_lap_choice_label():
    row = {"number": 20, "lap_time": 79.461, "description": "lap 20, Soft, 2 laps old",
           "notes": ["fastest"]}
    assert lap_choice_label(row) == "Lap 20 · 1:19.461 · Soft, 2 laps old · fastest"


# --- hover maths --------------------------------------------------------------------


def make_comparison():
    """A 1 km straight: LEC at 200 km/h on full throttle, NOR at 210 km/h on half."""
    distance = np.linspace(0, 1000, 101)
    tel = pd.DataFrame({"Distance": distance, "X": distance * 10, "Y": np.zeros_like(distance)})
    grid = np.linspace(0, 1000, 11)
    fields = dict.fromkeys(Comparison.__dataclass_fields__)
    fields.update(tels=[tel, tel], track=tel, distance_m=grid, labels=["LEC", "NOR"],
                  delta=np.linspace(0, -0.1, 11),
                  traces={"Speed (km/h)": (np.full(11, 200.0), np.full(11, 210.0)),
                          "Throttle (%)": (np.full(11, 100.0), np.full(11, 50.0))})
    return Comparison(**fields)


def test_point_at_gives_position_inputs_and_gap():
    point = point_at(make_comparison(), 500)
    assert point["x"] == pytest.approx(5000) and point["y"] == 0
    assert point["speed"] == (200, 210) and point["throttle"] == (100, 50)
    assert point["gap"] == pytest.approx(-0.05)


def test_distance_at_point_on_and_off_the_track():
    c = make_comparison()
    assert distance_at_point(c, 5000, 50) == pytest.approx(500)  # 5 m off the line
    assert distance_at_point(c, 5000, 5000) is None              # 500 m away


def test_hover_text():
    c = make_comparison()
    assert hover_text(c, point_at(c, 500)) == (
        "500 m   ·   LEC: 200 km/h, 100% throttle   ·   NOR: 210 km/h, 50% throttle"
        "   ·   NOR ahead by 0.050s")


# --- the window ---------------------------------------------------------------------

EVENTS = [{"round": 1, "name": "Bahrain Grand Prix",
           "sessions": ["Practice 1", "Qualifying", "Race"]},
          {"round": 2, "name": "Saudi Arabian Grand Prix", "sessions": ["Practice 1"]}]


@pytest.fixture
def window(qtbot, monkeypatch):
    """The app with fake loaders; compare_laps and message boxes are replaced too."""
    calls = {"schedule": [], "session": [], "compare": [], "warnings": []}

    def schedule_loader(year):
        calls["schedule"].append(year)
        return EVENTS

    def session_loader(year, round_, session_name):
        calls["session"].append((year, round_, session_name))
        return FakeSession()

    def fake_compare(session, drivers, laps):
        calls["compare"].append((drivers, laps))
        raise ValueError("no telemetry in this test")

    monkeypatch.setattr(app_module, "compare_laps", fake_compare)
    monkeypatch.setattr(app_module.QMessageBox, "warning",
                        lambda parent, title, message: calls["warnings"].append(message))
    w = MainWindow(schedule_loader=schedule_loader, session_loader=session_loader)
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: w.event.count() == 2)
    w.calls = calls
    yield w
    # Let background work finish before the window is cleaned up.
    app_module.QThreadPool.globalInstance().waitForDone(5000)


def items(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def test_calendar_loads_with_latest_event_selected(window):
    assert window.calls["schedule"] == [int(window.year.currentText())]
    assert window.event.currentText() == "Round 2: Saudi Arabian Grand Prix"
    assert items(window.session_name) == ["Practice 1"]


def test_qualifying_is_the_default_session(window):
    window.event.setCurrentIndex(0)
    assert items(window.session_name) == ["Practice 1", "Qualifying", "Race"]
    assert window.session_name.currentText() == "Qualifying"


def test_changing_season_reloads_the_calendar(window, qtbot):
    window.year.setCurrentText("2024")
    qtbot.waitUntil(lambda: window.calls["schedule"][-1] == 2024)


def test_loading_a_session_fills_drivers_and_laps_then_compares(window, qtbot):
    window.event.setCurrentIndex(0)
    window.on_load()
    qtbot.waitUntil(lambda: bool(window.calls["warnings"]))  # automatic first comparison ran
    assert window.calls["session"][-1][1:] == (1, "Qualifying")
    assert items(window.driver_a) == ["NOR", "PIA"]
    assert window.driver_b.currentText() == "PIA"
    # Laps without a time (out-laps here) aren't offered.
    assert items(window.lap_a) == ["Fastest lap", "Lap 2 · 1:19.300 · Soft, 2 laps old · fastest",
                                   "Lap 3 · 1:35.000 · Soft, 3 laps old · in-lap"]
    assert window.calls["compare"] == [(["NOR", "PIA"], [None, None])]
    assert window.calls["warnings"] == ["no telemetry in this test"]


def test_comparing_a_lap_with_itself_is_stopped_before_any_work(window, qtbot):
    window.event.setCurrentIndex(0)
    window.on_load()
    qtbot.waitUntil(lambda: bool(window.calls["warnings"]))
    window.driver_b.setCurrentText("NOR")
    window.on_compare()
    assert window.calls["warnings"][-1].startswith("both laps would be NOR's fastest lap")
    assert len(window.calls["compare"]) == 1  # only the automatic one from loading


def test_closing_during_a_load_does_not_crash(qtbot):
    import threading
    release = threading.Event()

    def slow_session_loader(year, round_, session_name):
        release.wait(5)  # still "downloading" when the window closes
        return FakeSession()

    w = MainWindow(schedule_loader=lambda year: EVENTS, session_loader=slow_session_loader)
    qtbot.waitUntil(lambda: w.event.count() == 2)
    w.event.setCurrentIndex(0)
    w.on_load()
    w.close()
    release.set()
    app_module.QThreadPool.globalInstance().waitForDone(5000)
    qtbot.wait(100)  # deliver the late result; it should be ignored
    assert w.closed and w.session is None


@pytest.mark.parametrize("area, canvas_geometry", [
    ((800, 600), (0, 50, 800, 500)),    # tall area: full width, centred vertically
    ((1000, 400), (180, 0, 640, 400)),  # wide area: full height, centred horizontally
])
def test_figure_scales_to_fit_without_changing_its_layout(qtbot, area, canvas_geometry):
    from matplotlib.figure import Figure
    from f1_deltaline.app import FitArea, FitCanvas
    from f1_deltaline.plot import FIGSIZE

    canvas = FitCanvas(Figure(figsize=FIGSIZE))
    fit = FitArea(canvas)
    qtbot.addWidget(fit)
    fit.resize(*area)
    fit.show()
    qtbot.waitExposed(fit)

    geometry = canvas.geometry()
    assert (geometry.x(), geometry.y(), geometry.width(), geometry.height()) == canvas_geometry
    width, height = canvas.figure.get_size_inches()
    assert width == pytest.approx(FIGSIZE[0], abs=0.02)   # same designed layout...
    assert height == pytest.approx(FIGSIZE[1], abs=0.02)
    ratio = canvas.device_pixel_ratio                      # ...drawn to fill every pixel
    assert canvas.figure.bbox.width == pytest.approx(canvas.width() * ratio)
    assert canvas.figure.bbox.height == pytest.approx(canvas.height() * ratio)


def test_data_notes_show_in_the_status_bar(window):
    window.show_data_notes(["No track map: no position data.", "Corners from Qualifying."])
    assert window.notes_label.text() == ("⚠ 2 data notes (hover for all): "
                                         "No track map: no position data.")
    assert window.notes_label.toolTip() == ("No track map: no position data.\n"
                                            "Corners from Qualifying.")
    window.show_data_notes(["Corners from Qualifying."])
    assert window.notes_label.text() == "⚠ Data note: Corners from Qualifying."
    window.show_data_notes([])
    assert window.notes_label.text() == "" and window.notes_label.toolTip() == ""


def test_long_data_notes_are_shortened_but_kept_in_full_in_the_tooltip(window):
    note = "Corner positions come from Qualifying, " * 10
    window.show_data_notes([note])
    text = window.notes_label.text()
    assert text.startswith("⚠ Data note: Corner positions") and text.endswith("…")
    assert window.notes_label.fontMetrics().horizontalAdvance(text) <= app_module.NOTES_MAX_WIDTH
    assert window.notes_label.toolTip() == note
