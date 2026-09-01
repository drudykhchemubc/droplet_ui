def parse_move(line: str, cx: float, cy: float, cz: float, feed: float):
    """Parse a G01 line's X/Y/Z/F tokens against the current position/feed.

    Returns (nx, ny, nz, feed_mm_s) — any axis/feed not present in the line
    is carried over unchanged from the passed-in current values.
    """
    nx, ny, nz = cx, cy, cz
    for token in line.split()[1:]:
        if   token[0] == 'X': nx = float(token[1:])
        elif token[0] == 'Y': ny = float(token[1:])
        elif token[0] == 'Z': nz = float(token[1:])
        elif token[0] == 'F': feed = float(token[1:]) / 60.0
    return nx, ny, nz, feed


def segment_time(
    dx: float, dy: float, dz: float, feed: float,
    max_rates: tuple[float, float, float], accels: tuple[float, float, float],
) -> float:
    """Time (seconds) for one linear move, modeled as GRBL would execute it.

    Args:
        dx, dy, dz: displacement in mm along each axis.
        feed:       vector feed rate in mm/s.
        max_rates:  per-axis max rates [X, Y, Z] in mm/s.
        accels:     per-axis accelerations [X, Y, Z] in mm/s².
    """
    dist = (dx*dx + dy*dy + dz*dz) ** 0.5
    if dist < 1e-9:
        return 0.0

    scales = [abs(dx) / dist, abs(dy) / dist, abs(dz) / dist]

    # Resultant velocity capped by per-axis max rates
    v = feed
    for i, s in enumerate(scales):
        if s > 1e-9:
            v = min(v, max_rates[i] / s)

    # Resultant acceleration capped by per-axis limits
    a = float('inf')
    for i, s in enumerate(scales):
        if s > 1e-9:
            a = min(a, accels[i] / s)
    if not (0 < a < float('inf')):
        a = min(accels) if min(accels) > 0 else 1.0

    # Trapezoidal velocity profile
    d_accel = v * v / (2.0 * a)
    if dist >= 2.0 * d_accel:
        return 2.0 * (v / a) + (dist - 2.0 * d_accel) / v
    else:
        return 2.0 * (dist / a) ** 0.5


def estimate_run_time(
    gcode_lines: list[str],
    feedrate_mmpm: float,
    max_rates_mmpm: tuple[float, float, float],
    accels_mmss: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Return (total_secs, dwell_secs, move_secs) for a G-code program (same model as GRBL / most 3-D printer slicers).

    Args:
        feedrate_mmpm:   Default feed rate in mm/min (overridden by F tokens).
        max_rates_mmpm:  Per-axis max rates [X, Y, Z] in mm/min  ($110–$112).
        accels_mmss:     Per-axis accelerations [X, Y, Z] in mm/s²  ($120–$122).
    """
    dwell_secs = sum(
        float(l.split('G04 P', 1)[1])
        for l in gcode_lines if l.startswith('G04 P')
    )

    max_rates = tuple(r / 60.0 for r in max_rates_mmpm)   # mm/min → mm/s
    accels    = tuple(accels_mmss)

    cx, cy, cz = 0.0, 0.0, 0.0
    feed = feedrate_mmpm / 60.0
    move_secs = 0.0

    for line in gcode_lines:
        if not line.startswith('G01'):
            continue
        nx, ny, nz, feed = parse_move(line, cx, cy, cz, feed)
        move_secs += segment_time(nx - cx, ny - cy, nz - cz, feed, max_rates, accels)
        cx, cy, cz = nx, ny, nz

    return dwell_secs + move_secs, dwell_secs, move_secs


def format_estimate(
    gcode_lines: list[str],
    feedrate_mmpm: float,
    max_rates_mmpm: tuple[float, float, float],
    accels_mmss: tuple[float, float, float],
) -> str:
    """Return a human-readable time estimate string, or '' if no G-code."""
    if not gcode_lines:
        return ""
    total, dwell, move = estimate_run_time(gcode_lines, feedrate_mmpm, max_rates_mmpm, accels_mmss)

    def fmt(s: float) -> str:
        return f"{int(s // 60)}m {int(s % 60)}s"

    return (
        f"Estimated run time: ~{fmt(total)}  "
        f"(dwell {fmt(dwell)} + movement {fmt(move)})"
    )
