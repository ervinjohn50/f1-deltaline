"""Mini-sector comparison logic. Pure NumPy so it can be tested without FastF1."""

import numpy as np


def sector_times(distance, time, n_sectors):
    """Time (seconds) a driver spent in each of n equal-length mini-sectors.

    Distance is normalised to 0..1 so laps of slightly different measured
    length can be compared sector for sector.
    """
    distance = np.asarray(distance, dtype=float)
    time = np.asarray(time, dtype=float)
    fraction = (distance - distance[0]) / (distance[-1] - distance[0])
    boundaries = np.linspace(0.0, 1.0, n_sectors + 1)
    times_at_boundaries = np.interp(boundaries, fraction, time)
    return np.diff(times_at_boundaries)


def sector_winners(times_a, times_b):
    """0 where driver A was faster in a mini-sector, 1 where driver B was."""
    return np.where(np.asarray(times_a) <= np.asarray(times_b), 0, 1)


def sector_index(distance, n_sectors):
    """Which mini-sector each telemetry sample falls into."""
    distance = np.asarray(distance, dtype=float)
    fraction = (distance - distance[0]) / (distance[-1] - distance[0])
    return np.minimum((fraction * n_sectors).astype(int), n_sectors - 1)
