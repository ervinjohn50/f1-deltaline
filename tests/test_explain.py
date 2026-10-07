import numpy as np
import pytest

from f1_deltaline.explain import (braking_runs, explain_lap, find_zones, group_corners,
                                  reasons, zone_gains, zone_metrics)

DISTANCE = np.arange(0, 3005, 5.0)  # a 3 km lap sampled every 5 m
CORNERS = [{"label": "1", "distance": 1000}, {"label": "2", "distance": 2200}]


def make_driver(brake_shift=0, corner2_min=150):
    """Speed, throttle and brake for a lap with two corners.

    Each corner: brake 200 m before it down to the minimum speed, then
    accelerate back to 300 km/h over 400 m. brake_shift moves the corner 2
    braking point (positive = later).
    """
    speed = np.full_like(DISTANCE, 300.0)
    brake = np.zeros_like(DISTANCE)
    throttle = np.full_like(DISTANCE, 100.0)
    for apex, slowest, shift in [(1000, 100, 0), (2200, corner2_min, brake_shift)]:
        brake_from = apex - 200 + shift
        braking = (DISTANCE >= brake_from) & (DISTANCE < apex)
        speed[braking] = np.interp(DISTANCE[braking], [brake_from, apex], [300, slowest])
        brake[braking] = 1
        throttle[braking] = 0
        exit_ = (DISTANCE >= apex) & (DISTANCE <= apex + 400)
        speed[exit_] = np.interp(DISTANCE[exit_], [apex, apex + 400], [slowest, 300])
        throttle[(DISTANCE >= apex) & (DISTANCE < apex + 50)] = 60
    return speed, throttle, brake


def test_group_corners_merges_close_corners():
    corners = [{"label": "1", "distance": 900}, {"label": "2", "distance": 950},
               {"label": "3", "distance": 1500}]
    groups = group_corners(corners)
    assert [g["labels"] for g in groups] == [["1", "2"], ["3"]]
    assert groups[0]["start"] == 900 and groups[0]["end"] == 950


def test_zones_cover_the_whole_lap_with_edges_at_fast_points():
    speed, _, _ = make_driver()
    zones = find_zones(DISTANCE, speed, group_corners(CORNERS))
    assert [z["name"] for z in zones] == ["the run to turn 1", "turn 1", "turn 2"]
    assert zones[0]["start"] == 0 and zones[-1]["end"] == DISTANCE[-1]
    for before, after in zip(zones, zones[1:]):
        assert before["end"] == after["start"]
    # Edges sit where the car is at top speed, not in a corner.
    for zone in zones[1:]:
        assert np.interp(zone["start"], DISTANCE, speed) == 300


def test_corners_without_a_straight_between_them_are_merged():
    # Corners 600 m apart, but speed never gets above 150 km/h between them.
    speed = np.where((DISTANCE > 800) & (DISTANCE < 2400), 150.0, 300.0)
    zones = find_zones(DISTANCE, speed, group_corners(CORNERS))
    assert [z["name"] for z in zones] == ["the run to turns 1-2", "turns 1-2"]


def test_zone_gains_add_up_to_the_final_gap():
    speed, _, _ = make_driver()
    zones = find_zones(DISTANCE, speed, group_corners(CORNERS))
    delta = np.sin(DISTANCE / 400) * 0.1 + DISTANCE * 0.00005
    assert sum(zone_gains(DISTANCE, delta, zones)) == pytest.approx(delta[-1] - delta[0])


def test_zone_metrics_finds_braking_apex_and_throttle():
    speed, throttle, brake = make_driver()
    m = zone_metrics(DISTANCE, speed, throttle, brake, 1500, 3000)
    assert m["brake_at"] == 2000
    assert m["min_speed"] == 150
    assert m["full_throttle_at"] == 2250
    assert m["top_speed"] == 300


def test_braking_that_starts_before_the_zone_edge_is_still_found():
    speed, throttle, brake = make_driver()
    m = zone_metrics(DISTANCE, speed, throttle, brake, 2100, 3000)  # edge after braking starts
    assert m["brake_at"] == 2000


def test_chicane_uses_the_first_braking_not_the_second_dab():
    on = np.array([0, 1, 1, 1, 0, 0, 1, 0], dtype=bool)
    assert braking_runs(on) == [(1, 3), (6, 6)]


def test_reasons_only_mentions_clear_differences():
    gainer = {"brake_at": 2020, "min_speed": 155, "full_throttle_at": 2240, "top_speed": 301}
    other = {"brake_at": 2000, "min_speed": 150, "full_throttle_at": 2250, "top_speed": 300}
    assert reasons(gainer, other) == ["braked 20 m later", "5 km/h faster at the slowest point",
                                      "back on full throttle 10 m earlier"]
    assert reasons(other, other) == []


def test_explain_lap_names_the_driver_corner_and_cause():
    a = make_driver()
    b = make_driver(brake_shift=20, corner2_min=158)
    traces = {"Speed (km/h)": (a[0], b[0]), "Throttle (%)": (a[1], b[1]), "Brake": (a[2], b[2])}
    # B loses nothing until turn 2, then gains 0.06 s there.
    delta = np.where(DISTANCE < 1900, 0.0, np.minimum((DISTANCE - 1900) / 300, 1) * -0.06)
    top = explain_lap(DISTANCE, delta, traces, CORNERS, ["LEC", "NOR"])
    assert len(top) == 1
    assert top[0]["gainer"] == 1
    assert top[0]["text"].startswith("NOR gained 0.060s at turn 2: braked 20 m later, "
                                     "8 km/h faster at the slowest point")


def test_explain_lap_without_corner_data_says_nothing():
    a = make_driver()
    traces = {"Speed (km/h)": (a[0], a[0]), "Throttle (%)": (a[1], a[1]), "Brake": (a[2], a[2])}
    assert explain_lap(DISTANCE, DISTANCE * 0.0001, traces, [], ["A", "B"]) == []
