import argparse

import pandas as pd
import pytest
from fastf1.core import Laps

from f1_deltaline.data import describe_lap, is_pit_lap, pick_lap, theoretical_best
from f1_deltaline.analysis import (check_lap_choices, resolve_drivers,
                                   theoretical_best_summary)
from main import parse_lap_choice


def seconds(values):
    """Timedeltas from seconds; None becomes 'no time' (NaT)."""
    return pd.to_timedelta(values, unit="s")


def make_laps(deleted=(), sector1=(None, 28.6, 28.7, 28.4)):
    """A driver's short qualifying run: out-lap, two timed laps, in-lap.

    Lap 3 is the fastest, but the best sector 1 is on lap 4.
    """
    return Laps(pd.DataFrame({
        "Driver": ["HAM"] * 4,
        "DriverNumber": ["44"] * 4,
        "LapNumber": [1.0, 2.0, 3.0, 4.0],
        "LapTime": seconds([None, 87.5, 86.2, 95.0]),
        "Sector1Time": seconds(list(sector1)),
        "Sector2Time": seconds([31.0, 29.9, 29.0, 31.0]),
        "Sector3Time": seconds([30.0, 29.0, 28.5, 35.6]),
        "Compound": ["SOFT", "SOFT", "SOFT", "SOFT"],
        "TyreLife": [1.0, 2.0, 3.0, 4.0],
        "PitOutTime": seconds([600, None, None, None]),
        "PitInTime": seconds([None, None, None, 1000]),
        "IsPersonalBest": [False, True, True, False],
        "Deleted": [n in deleted for n in (1, 2, 3, 4)],
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


def test_resolve_drivers():
    assert resolve_drivers(["ver", "ham"]) == ["VER", "HAM"]
    assert resolve_drivers(["ver"]) == ["VER", "VER"]
    with pytest.raises(ValueError, match="one or two drivers"):
        resolve_drivers(["VER", "HAM", "LEC"])


def test_check_lap_choices_allows_different_laps_or_drivers():
    check_lap_choices(["VER", "VER"], [5, 40])
    check_lap_choices(["VER", "VER"], [None, 40])
    check_lap_choices(["VER", "HAM"], [None, None])
    check_lap_choices(["VER", "HAM"], [12, 12])


def test_check_lap_choices_rejects_same_lap_twice():
    with pytest.raises(ValueError, match="VER's fastest lap"):
        check_lap_choices(["VER", "VER"], [None, None])
    with pytest.raises(ValueError, match="VER's lap 12"):
        check_lap_choices(["VER", "VER"], [12, 12])


def test_theoretical_best_uses_best_sector_from_any_lap():
    best = theoretical_best(make_laps(), "HAM")
    assert best["sectors"] == [(28.4, 4), (29.0, 3), (28.5, 3)]
    assert best["total"] == pytest.approx(85.9)


def test_theoretical_best_skips_deleted_laps():
    best = theoretical_best(make_laps(deleted=[4]), "HAM")
    assert best["sectors"][0] == (28.6, 2)
    assert best["total"] == pytest.approx(86.1)


def test_theoretical_best_missing_sector_returns_none():
    laps = make_laps()
    laps["Sector3Time"] = pd.NaT
    assert theoretical_best(laps, "HAM") is None


def test_theoretical_best_summary_time_left():
    printed, notes = theoretical_best_summary(make_laps(), ["HAM", "HAM"])
    assert len(printed) == 1  # same driver twice is listed once
    assert printed[0] == ("HAM theoretical best: 1:25.900 (S1 lap 4, S2 lap 3, S3 lap 3), "
                          "0.300s quicker than their fastest lap")
    assert notes == ["HAM theoretical best 1:25.900: 0.300s quicker than their fastest lap"]


def test_theoretical_best_summary_all_sectors_on_fastest_lap():
    laps = make_laps(deleted=[4], sector1=[None, 28.9, 28.7, 28.4])
    printed, _ = theoretical_best_summary(laps, ["HAM"])
    assert printed[0].endswith("all three best sectors on their fastest lap")
