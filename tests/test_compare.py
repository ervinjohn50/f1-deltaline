import numpy as np

from f1_deltaline.compare import sector_index, sector_times, sector_winners


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
