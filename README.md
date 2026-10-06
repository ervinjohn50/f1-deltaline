# F1 Deltaline

See exactly where on track one driver was faster than another.

F1 Deltaline loads two drivers' fastest laps and shows:

- **Track map** coloured by who was quicker in each mini-sector, with corner numbers
- **Gap chart**: the running time gap around the lap, so you can see where each
  driver gained and lost time
- **Speed, throttle and brake** for both drivers, lined up by distance

![Leclerc vs Norris, Monza 2024 qualifying](docs/example.png)

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Usage

```bash
uv run main.py --year 2024 --event Monza --session Q --drivers LEC NOR
```

| Option | Description |
|---|---|
| `--year` | Season, e.g. `2024` (telemetry is available from 2018) |
| `--event` | Event name or round number, e.g. `Monza` or `16` |
| `--session` | `R`, `Q`, `S`, `FP1`, `FP2`, `FP3` (default `Q`) |
| `--drivers` | Two driver abbreviations, e.g. `VER HAM` |
| `--sectors` | Number of mini-sectors (default `25`) |
| `--no-show` | Save the image without opening a window |

Images are saved to `output/`. Session data is cached in `.fastf1-cache/`, so
the first load of a session is slow and later loads are fast.

## How it works

1. **Load** the session with [FastF1](https://github.com/theOehrly/Fast-F1) and
   take each driver's fastest lap.
2. **Normalise** each lap's distance to 0–1, so laps of slightly different
   measured length line up.
3. **Split** the lap into equal mini-sectors and interpolate the time each
   driver reached every boundary. The difference is the time spent in that sector.
4. **Colour** the track by the driver with the lower time in each sector.
5. **Gap and traces**: resample both laps onto a shared grid of 1,000 points
   along the lap. The gap at each point is B's elapsed time minus A's, so where
   the line rises A is gaining and where it falls B is.

### Lap distance

Lap distance is calculated from speed and time using the trapezoid rule (the
average of each pair of speed readings). FastF1's built-in `Distance` instead
multiplies each reading by the time since the previous one, which comes up
several metres short under braking and long under acceleration. Because the
two drivers' readings fall at different moments, those errors differ and show
up as false spikes in the gap chart at slow corners. Switching to the trapezoid
rule cut the worst spike at Monza 2024 (LEC vs NOR) from 0.18s to 0.135s.

### Known limitation

Some short spikes remain in slow corners (e.g. Monza turns 4–5). Car data
arrives about four times a second, so at 300 km/h a car travels ~20 m between
readings. Part of what's left may be real (different braking points and
minimum speeds) and part is this sampling limit; the data can't fully tell them
apart. The overall trend and the gap at the finish line are accurate.

## Tests

```bash
uv run pytest
```

## Credits

Inspired by [f1-race-replay](https://github.com/IAmTomShaw/f1-race-replay).
Data via [FastF1](https://github.com/theOehrly/Fast-F1).

F1 Deltaline is an unofficial fan project and is not affiliated with Formula 1
or the FIA.
