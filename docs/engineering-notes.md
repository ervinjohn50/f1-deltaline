# Engineering notes

Problems found while building F1 Deltaline, what caused them, how they were
fixed, and how each fix was checked. Numbers come from real sessions unless
stated otherwise.

- [Data accuracy](#data-accuracy)
- [Explaining the gap](#explaining-the-gap)
- [Gaps in F1's data](#gaps-in-f1s-data)
- [Desktop app](#desktop-app)
- [Tooling](#tooling)

## Data accuracy

### False spikes in the gap chart

**Problem.** The gap chart showed short spikes in slow corners: at Monza 2024
qualifying (LEC vs NOR) the gap jumped from 0.2s to 0.37s and back within about
100 m at turns 4–5. A real gap can't swing that much that quickly.

**Cause.** FastF1 works out distance by multiplying each speed reading by the
time since the previous one. Under hard braking speed drops a lot between
readings, so this comes up a few metres short, and it overshoots under
acceleration. The two cars' readings fall at different moments, so their errors
differ. At low speed a few metres is a lot of time (error ≈ distance error ÷
speed: 5 m at 90 km/h is about 0.2s), so the spikes appear in slow corners.

**Fix.** Distance is now calculated with the trapezoid rule, averaging each pair
of speed readings (`integrate_distance` in `compare.py`).

**Checked.** The largest spike that reverses within 150 m:

| Method | Monza (LEC vs NOR) | Silverstone (HAM vs RUS) | Final gaps |
|---|---|---|---|
| FastF1's distance | 0.180s | 0.098s | 0.134s / 0.171s |
| Aligning on track position (rejected, below) | 0.232s | 0.251s | unchanged |
| **Trapezoid rule** | **0.135s** | **0.090s** | unchanged |

A test shows FastF1's method coming up more than 5 m short over a steady 4-second
stop from 300 to 100 km/h, while the trapezoid rule is exact.

### An idea that made it worse: aligning laps on track position

The first attempt measured both laps along driver A's actual line on track,
matching each of driver B's X/Y positions to the nearest point. It made the
spikes worse (table above): position data is noisier than distance worked out
from speed. It was measured, rejected and removed.

### What's left

Some short spikes remain (Monza turns 4–5 still peaks at 0.27s, down from
0.37s). Car data arrives about four times a second, roughly 20 m apart at
300 km/h, and part of what's left may be real (different braking points and
minimum speeds). The data can't separate the two. The overall trend and the gap
at the finish line are accurate, and the corner-by-corner summary is designed
not to depend on these spikes (next section).

## Explaining the gap

### Zone edges at low speed weren't reliable

**Problem.** The summary splits the lap into zones, one per corner, and measures
the gap change across each. At Silverstone the edge between Brooklands (turn 6)
and Luffield (turn 7) fell at about 190 km/h, because there's no real straight
between them. Edges at low speed pick up exactly the error described above:
the first version reported "HAM gained 0.074s at turn 6".

**Fix.** Zone edges sit at the fastest point between corners, and corners with
no real straight between them (fastest point under 70% of the lap's top speed)
are merged into one zone. Silverstone now reports "HAM gained 0.053s at turns
6-7".

**Checked.** The zone gains always add up exactly to the final gap (Monza
−0.134s, Silverstone −0.171s), and a test checks this.

### The wrong braking point in chicanes

**Problem.** At Monza's first chicane the braking point came out as 934 m for
both drivers, when they actually braked at 767 m and 790 m.

**Cause.** In a chicane drivers brake hard for the first corner, then dab the
brakes for the second. The code took the last braking stretch before the
slowest point, which was the dab.

**Fix.** The braking point is the start of the first braking stretch that
reaches into the zone. It may begin before the zone edge, so the search looks up
to 150 m back.

### Smaller fixes

- **Deleted laps.** Laps deleted for track limits only show up if FastF1 also
  loads race control messages, which it now does, so they're left out of the
  theoretical best and marked in `--list-laps`.
- **"Fastest" lap marking.** FastF1's `IsPersonalBest` marks every lap that was a
  personal best *when it was set*, so several laps were labelled. Only the
  driver's actual fastest lap is marked now.

## Gaps in F1's data

### The 2026 Monaco race crashed with `KeyError: 'Date'`

**Problem.** Loading the 2026 Monaco race and comparing any two fastest laps
failed with a `KeyError` from inside FastF1.

**Cause.** The race's position data (where each car is on track) stops partway
through: for one driver it ends 1 hour 52 minutes into the session, while car
data (speed, throttle, brake) runs to 3 hours 22 minutes, with about 8,000
position readings against 45,000 car readings. Most fastest laps came near the
end, after it stops. FastF1 needs both to build a lap, so it failed. Monaco
qualifying worked, and the other 2026 races checked (Australia, Azerbaijan,
Bahrain) had position data for every driver.

**Fixes.**
- Laps with no position data are built from car data alone. Distance comes from
  speed, not position, so everything except the track map still works.
- The track map uses lap B's position data if only lap A is missing it, and
  otherwise says "Track map unavailable".
- FastF1 also needs position data to place corners, so the corner-by-corner
  summary had nothing to work with. Corners are now borrowed from another
  session of the same event (qualifying first, at most two sessions tried), since
  the track is the same all weekend.
- Drivers with no timed lap (e.g. out on lap 1) are left out of the driver lists
  instead of causing a "no timed lap" error.

**Checked.** Building a complete lap (Monza 2024 qualifying, LEC vs NOR) from
car data alone gave the same lap length (5,761 m), the same final gap (−0.134s)
and the same gap mid-lap as the normal method. The Monaco race now compares
normally: "ANT gained 0.401s at turns 12-19: braked 16 m later".

### Telling the user about data problems

FastF1 prints dozens of warnings about F1's data, which in the desktop app were
only noise in the terminal. The app now hides them and shows **data notes** in
the status bar for the problems that actually affect a comparison: no or partial
track map, borrowed corners, and gaps in a lap's car data. The command line
prints the same notes.

The car-data gap threshold came from real laps: even clean laps have the odd gap
of up to about 1.1s between readings (Monza and Silverstone 2024), and the
Monaco race's worst was 1.28s. Flagging anything over 1s would have warned on
most laps, so only gaps over 2s (about 170 m at top speed) are reported.

## Desktop app

### Keeping the command line identical

Moving the analysis out of `main.py` so the app could share it was checked by
saving the output of six command-line runs (four comparisons, a lap list and an
error) before the change and comparing afterwards: all text and all four images
were identical, pixel for pixel. The same check was repeated after later changes
to shared code.

### Closing the window during a download crashed Python

**Cause.** The download finished after the window was gone, and its result tried
to update widgets that no longer existed.

**Fix.** The window remembers it's been closed and ignores late results. A test
closes the window during a slow fake download.

### "Recursive repaint detected" warnings

**Cause.** After each full redraw (first draw, resize, toolbar zoom) the hover
cursor asked Qt to repaint, while Qt was already painting. Reproduced in a real
window: one set of warnings per redraw.

**Fix.** On a full redraw the cursor is drawn straight into the new image, as
matplotlib's animation guide recommends; the separate repaint is only used when
the mouse moves.

### Overlapping text in smaller windows

**Cause.** Matplotlib's Qt canvas keeps text the same size and stretches the
layout to the window. Below the designed size (about 1600×1050) the spaces
shrank but the text didn't, so the legend ran into the lines below it.

**Fix.** The figure is scaled to fit the window instead, keeping its designed
16×10 layout (the same as the saved images), centred in the available space.

**Checked** in a real window at four sizes, with mouse hover landing on exactly
the right distance at each:

| Window | Figure scale |
|---|---|
| 1600×1050 | 84% |
| 1440×900 | 75% |
| 1280×800 | 65% |
| 1024×700 | 55% |

A follow-up bug: rounding made the figure one pixel shorter than its space, so
the last row was never redrawn and showed leftovers from the previous size. The
figure is now sized from the exact pixel count; a test checks it fills its space.

### Repeated work on every comparison

For sessions that borrow corners, every Compare reopened the other session: about
1 second each time on the 2026 Monaco race with qualifying already cached, and
much longer if it had to be downloaded. The result is now remembered per session,
so only the first comparison pays for it (a second one took 0.2s in the app,
including drawing).

### Quitting

- **Ctrl+C was ignored.** Qt's event loop keeps Python from handling it; the app
  was still running 10 seconds after Ctrl+C. The default behaviour is restored,
  so Ctrl+C quits immediately.
- **Closing during a download left the terminal busy** (a 5-second fake download
  kept the process alive 5 seconds after the window closed). Stopping a FastF1
  download halfway could leave a broken file in its cache, so the app still
  finishes it, but now says so in the terminal; Ctrl+C quits straight away.

### Install size

The full `pyside6` package made the environment 1.4 GB, mostly Qt modules this
app doesn't use (web engine, 3D). `pyside6-essentials` has everything it needs
at 595 MB.

## Tooling

- **Tests run offline.** None of the tests download race data: the analysis is
  tested on made-up laps with known answers, and the app with fake loaders. This
  was checked by running the suite with network access blocked.
- **GitHub Actions couldn't start.** The workflow used `astral-sh/setup-uv@v10`,
  but setup-uv only publishes full version tags (e.g. `v10.2.0`), so GitHub
  couldn't find it. It's now pinned to the full version.
