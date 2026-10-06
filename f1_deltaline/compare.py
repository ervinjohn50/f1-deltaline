"""Lap comparison logic. Pure NumPy so it can be tested without FastF1.

Distances are normalised to 0..1 of the lap so laps of slightly different
measured length can be compared point for point.
"""

import numpy as np


def lap_fraction(distance):
    """Distance along the lap as a fraction from 0 (start) to 1 (finish)."""
    distance = np.asarray(distance, dtype=float)
    return (distance - distance[0]) / (distance[-1] - distance[0])


def sector_times(distance, time, n_sectors):
    """Time (seconds) a driver spent in each of n equal-length mini-sectors."""
    boundaries = np.linspace(0.0, 1.0, n_sectors + 1)
    times_at_boundaries = np.interp(boundaries, lap_fraction(distance), time)
    return np.diff(times_at_boundaries)


def sector_winners(times_a, times_b):
    """0 where driver A was faster in a mini-sector, 1 where driver B was."""
    return np.where(np.asarray(times_a) <= np.asarray(times_b), 0, 1)


def sector_index(distance, n_sectors):
    """Which mini-sector each telemetry sample falls into."""
    fraction = lap_fraction(distance)
    return np.minimum((fraction * n_sectors).astype(int), n_sectors - 1)


def resample(distance, values, grid):
    """Values (speed, throttle...) interpolated onto a shared 0..1 lap grid."""
    return np.interp(grid, lap_fraction(distance), np.asarray(values, dtype=float))


def time_delta(distance_a, time_a, distance_b, time_b, grid):
    """Running gap in seconds at each grid point: B's elapsed time minus A's.

    Positive means A is ahead at that point of the lap; where the line rises,
    A is gaining time, and where it falls, B is.
    """
    time_a = np.asarray(time_a, dtype=float)
    time_b = np.asarray(time_b, dtype=float)
    elapsed_a = resample(distance_a, time_a - time_a[0], grid)
    elapsed_b = resample(distance_b, time_b - time_b[0], grid)
    return elapsed_b - elapsed_a
