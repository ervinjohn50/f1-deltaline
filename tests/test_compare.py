import numpy as np

from f1_deltaline.compare import (integrate_distance, resample, sector_index, sector_times,
                                  sector_winners, time_delta)


def test_constant_speed_gives_equal_sector_times():
    distance = np.linspace(0, 1000, 101)
    time = distance / 50  # 50 m/s, 20 s lap
    times = sector_times(distance, time, 4)
    assert np.allclose(times, [5, 5, 5, 5])
    assert np.isclose(times.sum(), 20)


def test_slower_section_shows_up_in_right_sector():
    distance = np.linspace(0, 1000, 1001)
    speed = np.where(distance < 500, 50.0, 25.0)  # second half twice as slow
    time = np.concatenate([[0], np.cumsum(np.diff(distance) / speed[1:])])
    times = sector_times(distance, time, 2)
    assert np.allclose(times, [10, 20], atol=0.05)


def test_laps_of_different_measured_length_are_normalised():
    a = sector_times(np.linspace(0, 1000, 50), np.linspace(0, 20, 50), 5)
    b = sector_times(np.linspace(0, 1010, 50), np.linspace(0, 20, 50), 5)
    assert np.allclose(a, b)


def test_sector_winners():
    assert list(sector_winners([1.0, 2.0, 3.0], [1.5, 1.9, 3.0])) == [0, 1, 0]


def test_sector_index_covers_every_sector_and_clamps_the_end():
    idx = sector_index(np.linspace(0, 100, 11), 5)
    assert idx[0] == 0 and idx[-1] == 4
    assert set(idx) == {0, 1, 2, 3, 4}


def test_time_delta_grows_steadily_when_a_is_always_faster():
    distance = np.linspace(0, 1000, 201)
    grid = np.linspace(0, 1, 11)
    delta = time_delta(distance, distance / 50, distance, distance / 40, grid)  # 20 s vs 25 s
    assert np.isclose(delta[0], 0)
    assert np.isclose(delta[-1], 5)
    assert np.allclose(delta, np.linspace(0, 5, 11))


def test_time_delta_shows_b_gaining_back_in_second_half():
    distance = np.linspace(0, 1000, 1001)
    a_speed = np.where(distance < 500, 50.0, 25.0)  # A: 10 s + 20 s
    b_speed = np.where(distance < 500, 25.0, 50.0)  # B: 20 s + 10 s
    seconds = lambda speed: np.concatenate([[0], np.cumsum(np.diff(distance) / speed[1:])])
    grid = np.array([0.0, 0.5, 1.0])
    delta = time_delta(distance, seconds(a_speed), distance, seconds(b_speed), grid)
    assert np.allclose(delta, [0, 10, 0], atol=0.05)  # A 10 s up at halfway, level at the end


def test_time_delta_ignores_time_offset_at_lap_start():
    distance = np.linspace(0, 1000, 50)
    grid = np.linspace(0, 1, 5)
    delta = time_delta(distance, 100 + distance / 50, distance, 7 + distance / 50, grid)
    assert np.allclose(delta, 0)


def test_resample_onto_lap_grid():
    distance = np.array([0.0, 500.0, 1000.0])
    speed = np.array([100.0, 200.0, 300.0])
    assert np.allclose(resample(distance, speed, np.array([0, 0.25, 1])), [100, 150, 300])


def test_integrate_distance_constant_speed():
    seconds = np.linspace(0, 10, 41)
    distance = integrate_distance(np.full(41, 180.0), seconds)  # 180 km/h = 50 m/s
    assert distance[0] == 0
    assert np.isclose(distance[-1], 500)


def test_integrate_distance_is_exact_under_steady_braking():
    # Braking from 300 to 100 km/h over 4 s, sampled every 0.25 s like real car data.
    seconds = np.arange(0, 4.25, 0.25)
    speed = np.linspace(300, 100, len(seconds))
    expected = (300 + 100) / 2 / 3.6 * 4  # average speed x time = 222.2 m
    assert np.isclose(integrate_distance(speed, seconds)[-1], expected)

    # FastF1's method (each reading x time since the previous one) comes up metres short.
    rectangle = np.sum(speed[1:] / 3.6 * np.diff(seconds))
    assert expected - rectangle > 5
