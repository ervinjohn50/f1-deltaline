import argparse

import pandas as pd
import pytest
from fastf1.core import Laps

from f1_deltaline.data import describe_lap, is_pit_lap, pick_lap
from main import parse_lap_choice

def seconds(values):
    """Timedeltas from seconds; None becomes 'no time' (NaT)."""
    return pd.to_timedelta(values, unit="s")


def make_laps():
    """A driver's short qualifying run: out-lap, two timed laps, in-lap."""
    return Laps(pd.DataFrame({
        "Driver": ["HAM"] * 4,
        "DriverNumber": ["44"] * 4,
        "LapNumber": [1.0, 2.0, 3.0, 4.0],
        "LapTime": seconds([None, 87.5, 86.2, 95.0]),
        "Compound": ["SOFT", "SOFT", "SOFT", "SOFT"],
        "TyreLife": [1.0, 2.0, 3.0, 4.0],
        "PitOutTime": seconds([600, None, None, None]),
        "PitInTime": seconds([None, None, None, 1000]),
        "IsPersonalBest": [False, True, True, False],
        "Deleted": [False, False, False, False],
    }))


def test_pick_lap_by_number():
    assert pick_lap(make_laps(), "HAM", 2)["LapNumber"] == 2


def test_pick_lap_defaults_to_fastest():
    assert pick_lap(make_laps(), "HAM")["LapNumber"] == 3


def test_pick_lap_missing_lap_lists_range():
    with pytest.raises(ValueError, match=r"HAM has no lap 9 \(laps 1-4\)"):
        pick_lap(make_laps(), "HAM", 9)


def test_pick_lap_without_time_is_rejected():
    with pytest.raises(ValueError, match="no lap time"):
        pick_lap(make_laps(), "HAM", 1)


def test_pick_lap_unknown_driver():
    with pytest.raises(ValueError, match="No laps found for VER"):
        pick_lap(make_laps(), "VER", 2)


def test_is_pit_lap():
    laps = make_laps()
    assert [is_pit_lap(laps.iloc[i]) for i in range(4)] == [True, False, False, True]


def test_describe_lap():
    laps = make_laps()
    assert describe_lap(laps.iloc[0]) == "lap 1, Soft, 1 lap old"
    assert describe_lap(laps.iloc[2]) == "lap 3, Soft, 3 laps old"


def test_parse_lap_choice():
    assert parse_lap_choice("12") == 12
    assert parse_lap_choice("fastest") is None
    assert parse_lap_choice("F") is None
    for bad in ["abc", "0", "-3", "1.5"]:
        with pytest.raises(argparse.ArgumentTypeError):
            parse_lap_choice(bad)
