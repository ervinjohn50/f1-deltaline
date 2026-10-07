"""Where a lap was won and lost, in plain English. Pure NumPy, like compare.py.

The lap is split into zones, one per corner (or group of corners close
together, like a chicane). A zone runs from the fastest point before the
corner, where braking starts, to the fastest point before the next corner,
so it covers braking, the corner itself, the exit and the following straight.

Zone edges sit at the fastest points on the lap. That's where distance
errors matter least (an error of a few metres costs very little time at
300 km/h), so the gap change across a zone is reliable even where the
gap chart has short spikes inside a slow corner.
"""

import numpy as np

CORNER_GROUP_GAP_M = 200  # corners closer than this count as one complex
MIN_EDGE_SPEED = 0.7  # zone edges must be at least this fraction of the lap's top speed
BRAKE_LOOKBACK_M = 150  # braking can start a little before the zone edge

# Smallest differences worth mentioning. Car data arrives about 4 times a
# second (~20 m apart at 300 km/h), so smaller distance differences aren't reliable.
MIN_GAIN_S = 0.02
MIN_DISTANCE_M = 10
MIN_SPEED_KMH = 3
BRAKE_ON = 0.5
FULL_THROTTLE = 95


def group_corners(corners, max_gap=CORNER_GROUP_GAP_M):
    """Corners close together merged into groups: [{"labels": [...], "start": m, "end": m}]."""
    groups = []
    for corner in sorted(corners, key=lambda c: c["distance"]):
        if groups and corner["distance"] - groups[-1]["end"] < max_gap:
            groups[-1]["labels"].append(corner["label"])
            groups[-1]["end"] = corner["distance"]
        else:
            groups.append({"labels": [corner["label"]], "start": corner["distance"],
                           "end": corner["distance"]})
    return groups


def group_name(labels):
    return f"turn {labels[0]}" if len(labels) == 1 else f"turns {labels[0]}-{labels[-1]}"


def find_zones(distance_m, speed, groups, min_edge_speed=MIN_EDGE_SPEED):
    """Zones as [{"name", "start", "end"}], with edges at the fastest point between corners.

    Corners with no real straight between them (the fastest point between them
    is below min_edge_speed x the lap's top speed) are merged into one zone,
    because a zone edge at low speed isn't reliable.
    """
    distance_m = np.asarray(distance_m, dtype=float)
    speed = np.asarray(speed, dtype=float)
    groups = [dict(g, labels=list(g["labels"])) for g in groups]

    def fastest_point(start, end):
        inside = (distance_m >= start) & (distance_m <= end)
        if not inside.any():
            return (start + end) / 2, 0.0
        i = np.argmax(speed[inside])
        return distance_m[inside][i], speed[inside][i]

    while True:
        edges = [fastest_point(distance_m[0] if i == 0 else groups[i - 1]["end"], group["start"])
                 for i, group in enumerate(groups)]
        slow = [i for i in range(1, len(groups)) if edges[i][1] < min_edge_speed * speed.max()]
        if not slow:
            break
        i = slow[0]  # merge group i into the one before it, then look again
        groups[i - 1]["labels"] += groups[i]["labels"]
        groups[i - 1]["end"] = groups[i]["end"]
        del groups[i]
    edges = [distance for distance, _ in edges]

    zones = [{"name": "the run to " + group_name(groups[0]["labels"]),
              "start": distance_m[0], "end": edges[0]}] if groups else []
    for i, group in enumerate(groups):
        end = edges[i + 1] if i + 1 < len(groups) else distance_m[-1]
        zones.append({"name": group_name(group["labels"]), "start": edges[i], "end": end})
    return zones


def zone_gains(distance_m, delta, zones):
    """Change in the gap across each zone; positive means driver A gained there."""
    return [float(np.interp(z["end"], distance_m, delta) - np.interp(z["start"], distance_m, delta))
            for z in zones]


def zone_metrics(distance_m, speed, throttle, brake, start, end):
    """Braking point, slowest speed, full-throttle point and top speed in one zone."""
    d = np.asarray(distance_m, dtype=float)
    v, t, b = (np.asarray(x, dtype=float) for x in (speed, throttle, brake))
    inside = np.flatnonzero((d >= start) & (d <= end))
    slowest = inside[np.argmin(v[inside])]

    # Braking point: the start of the first braking stretch that reaches into the zone.
    # It may begin a little before the zone edge. Taking the first one matters in a
    # chicane, where a short second dab of the brakes comes after the main stop.
    brake_at = None
    earliest = np.searchsorted(d, start - BRAKE_LOOKBACK_M)
    for run_start, run_end in braking_runs(b[earliest:slowest + 1] >= BRAKE_ON):
        if d[earliest + run_end] >= start:
            brake_at = d[earliest + run_start]
            break

    after = inside[inside >= slowest]
    full = after[t[after] >= FULL_THROTTLE]
    return {
        "brake_at": brake_at,
        "min_speed": v[slowest],
        "full_throttle_at": d[full[0]] if full.size else None,
        "top_speed": v[after].max(),
    }


def braking_runs(on):
    """(first, last) index of each stretch where `on` is True, in order."""
    on = np.asarray(on, dtype=bool)
    edges = np.diff(np.concatenate([[False], on, [False]]).astype(int))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1))


def reasons(gainer, other):
    """What the faster driver in a zone did better, as short phrases."""
    found = []
    if gainer["brake_at"] is not None and other["brake_at"] is not None:
        later = gainer["brake_at"] - other["brake_at"]
        if later >= MIN_DISTANCE_M:
            found.append(f"braked {later:.0f} m later")
    faster = gainer["min_speed"] - other["min_speed"]
    if faster >= MIN_SPEED_KMH:
        found.append(f"{faster:.0f} km/h faster at the slowest point")
    if gainer["full_throttle_at"] is not None and other["full_throttle_at"] is not None:
        earlier = other["full_throttle_at"] - gainer["full_throttle_at"]
        if earlier >= MIN_DISTANCE_M:
            found.append(f"back on full throttle {earlier:.0f} m earlier")
    top = gainer["top_speed"] - other["top_speed"]
    if top >= MIN_SPEED_KMH:
        found.append(f"{top:.0f} km/h faster at the end of the straight")
    return found


def explain_lap(distance_m, delta, traces, corners, labels, top_n=3):
    """The biggest gains, most important first, as dicts with a plain-English "text".

    Each has "zone", "gain" (seconds), "gainer" (0 for driver A, 1 for B) and "text".
    traces: {"Speed (km/h)": (a, b), "Throttle (%)": (a, b), "Brake": (a, b)}
    Returns [] when there's no corner data or no zone changed the gap by MIN_GAIN_S.
    """
    speeds = traces["Speed (km/h)"]
    zones = find_zones(distance_m, (np.asarray(speeds[0]) + np.asarray(speeds[1])) / 2,
                       group_corners(corners))
    gains = zone_gains(distance_m, delta, zones)

    top = []
    for zone, gain in sorted(zip(zones, gains), key=lambda zg: -abs(zg[1]))[:top_n]:
        if abs(gain) < MIN_GAIN_S:
            break
        g = 0 if gain > 0 else 1
        metrics = [zone_metrics(distance_m, traces["Speed (km/h)"][i], traces["Throttle (%)"][i],
                                traces["Brake"][i], zone["start"], zone["end"]) for i in (0, 1)]
        why = reasons(metrics[g], metrics[1 - g]) or ["no single clear cause in the data"]
        top.append({"zone": zone, "gain": abs(gain), "gainer": g,
                    "text": f"{labels[g]} gained {abs(gain):.3f}s at {zone['name']}: "
                            f"{', '.join(why)}"})
    return top
