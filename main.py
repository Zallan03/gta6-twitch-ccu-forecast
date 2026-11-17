#!/usr/bin/env python3
"""Forecast GTA VI's launch-day Twitch concurrent viewers, hour by hour.

make.fun bounty: gta6-twitch-ccu-forecast-01
Entrypoint: python3 -P -s /bot/main.py (Python 3.13, standard library only)

Grading I/O contract (kit RULES.txt, "Your input" / "Your forecast"):
  - The grader runs this program once per case. It reads every <id>.in file
    in $MAKEFUN_INPUT_DIR (else /input/): one JSON object, schema
    "makefun/twitch-ccu-case/v1", with `known` (hour 1's print), `forecast`
    (the 23 rows to forecast, hours 2-24), `history`, `history_hourly`,
    `streams`, `categories_hourly`, `comparables` (past big launches' hourly
    Twitch counts) and `notes`.
  - It writes one file per case to $MAKEFUN_OUTPUT_DIR (else /output/):
    /output/<id>.out, UTF-8 JSON, exactly {"hours": [{"hour": h,
    "q": [q05, q25, q50, q75, q95]}, ...]} for h = 2..24, five quantiles at
    levels 0.05/0.25/0.5/0.75/0.95, each a finite number > 0 and <= 1e9,
    non-decreasing, at most 65,536 bytes. Anything else is an invalid case.
  - No network, no wall clock, no randomness: the forecast is a pure
    function of the case file, so two runs on the same case are
    byte-identical (the grader runs each case twice and compares).
  - Score: mean pinball loss on the log scale over every scored hour and
    quantile. A prize needs a loss strictly below the best house entry's.

Model (transparent, deterministic, stdlib-only)
-----------------------------------------------
A comparable-launch quantile model, anchored on the case's own hour-1
print p1 (the `known` row for hour 1; a print below 1 counts as 1):

1. SHAPE: for each forecast hour h (2..24), look at every comparable
   launch that has a viewer count for both its release-day hour 1 and
   hour h, and take the log-ratio ln(viewers_h / viewers_1). The median
   of those log-ratios is the hour's typical log growth over hour 1.
   Medians are robust to the odd launch whose unlock hour falls outside
   the UTC day, and the comparables are the launches the case itself
   ships, so nothing is tuned on the case being forecast.
2. SPREAD: the five quantiles are the EMPIRICAL quantiles of the same
   log-ratios at the scored levels (linear interpolation, the standard
   quantile definition): q_tau(h) = p1 * exp(Q_tau), where Q_tau is the
   tau-quantile of the hour's log-ratios. A pinball loss is a proper
   scoring rule for quantiles, so the forecast scores best by writing
   the quantiles it really believes; the empirical quantiles are the
   calibrated choice for a skewed distribution, where a symmetric
   log-normal spread would overstate both tails. Quantiles are rounded
   to 2 decimals (half up, like the house baseline's starter).
3. FALLBACK: when fewer than 8 comparables carry both hours (sparse
   sampling leaves some launches without a point for an hour), fall back
   to the fixed launch-day profile shape used by the first build of this
   entry, with the house baseline's widening spread: m_h =
   ln(profile[h-1] / profile[0]), s_h = 0.15 * sqrt(h - 1).

Local run:
    mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
Self-test (no case files needed):
    python3 main.py --self-test
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so an
# `import model` would find a model.py shipped beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

MODEL_VERSION = "gta6-ccv-forecast/2.0.0"

# The quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level.
Z = [-1.645, -0.674, 0, 0.674, 1.645]

# Fallback hourly profile: fraction of peak CCV for each hour since launch
# (hour 0 is the launch hour). Used only when too few comparables carry an
# hour; the primary shape comes from the case's comparables.
HOURLY_PROFILE = (
    0.62, 0.55, 0.48, 0.40, 0.34, 0.31, 0.32, 0.38,
    0.46, 0.54, 0.62, 0.69, 0.75, 0.80, 0.85, 0.89,
    0.93, 0.96, 0.99, 1.00, 0.98, 0.94, 0.87, 0.76,
)
# Fallback log spread per square-root hour (the house baseline's sigma).
FALLBACK_SIGMA = 0.15
# Minimum comparables with both hours before the empirical shape is used.
MIN_COMPARABLES = 8

MAX_QUANTILE = 1_000_000_000
MIN_QUANTILE = 0.01


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (trailing Z allowed)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def round2(x: float) -> float | int:
    """x rounded to 2 decimals, half up, as JavaScript's
    Math.round(x * 100) / 100 rounds it (same helper as the starter).

    A whole number comes back as an int, so json.dumps writes 1240 where
    JavaScript writes 1240 (not 1240.0).
    """
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def hourly_viewers(comparable: dict) -> dict[datetime, float]:
    """A comparable's hourly viewer counts, keyed by hour start (UTC)."""
    out: dict[datetime, float] = {}
    for row in comparable.get("hourly", []):
        try:
            viewers = float(row["viewers"])
        except (KeyError, TypeError, ValueError):
            continue
        if viewers <= 0:
            continue
        try:
            out[parse_ts(row["from"])] = viewers
        except (KeyError, TypeError, ValueError):
            continue
    return out


def log_ratios(case: dict, hour: int) -> list[float]:
    """ln(viewers_h / viewers_1) over the comparables that carry both
    release-day hour 1 and hour `hour` of their own launch day."""
    ratios: list[float] = []
    for comparable in sorted(case.get("comparables", []),
                             key=lambda c: str(c.get("name", ""))):
        try:
            day_start = parse_ts(comparable["day_start"])
        except (KeyError, TypeError, ValueError):
            continue
        by_hour = hourly_viewers(comparable)
        first = by_hour.get(day_start)
        later = by_hour.get(day_start + timedelta(hours=hour - 1))
        if first is None or later is None or first <= 0 or later <= 0:
            continue
        ratios.append(math.log(later / first))
    return ratios


def quantile(sorted_values: list[float], tau: float) -> float:
    """Linear-interpolation quantile of an already sorted list (the
    standard definition: numpy's 'linear' method). Deterministic."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    pos = tau * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def hour_quantiles(p1: float, case: dict, hour: int) -> list[float | int]:
    """The five quantiles of hour `hour`'s viewer count: the empirical
    quantiles of the comparables' log-ratios, scaled by the case's own
    hour-1 print."""
    ratios = sorted(log_ratios(case, hour))
    if len(ratios) >= MIN_COMPARABLES:
        values = [p1 * math.exp(quantile(ratios, tau)) for tau in LEVELS]
    else:
        # Fallback: fixed profile shape, house baseline's widening spread.
        centre = math.log(HOURLY_PROFILE[hour - 1] / HOURLY_PROFILE[0])
        spread = FALLBACK_SIGMA * math.sqrt(hour - 1)
        values = [p1 * math.exp(centre + z * spread) for z in Z]
    quantiles: list[float | int] = []
    previous = 0.0
    for value in values:
        value = min(max(value, MIN_QUANTILE), MAX_QUANTILE)
        value = round2(value)
        # Rounding must never break the non-decreasing order.
        if value < previous:
            value = previous
        quantiles.append(value)
        previous = float(value)
    return quantiles


def forecast_case(case: dict, name: str) -> dict:
    """Forecast one case: {"hours": [{"hour": h, "q": [...]}, ...]}."""
    first = next((k for k in case.get("known", []) if k.get("hour") == 1),
                 None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1, float(first["viewers"]))
    rows = []
    for row in case.get("forecast", []):
        hour = int(row["hour"])
        rows.append({"hour": hour,
                     "q": hour_quantiles(p1, case, hour)})
    if len(rows) != 23:
        raise ValueError(f"{name}: expected 23 forecast rows, got {len(rows)}")
    return {"hours": rows}


def validate_output(payload: dict) -> list[str]:
    """Strict checks of an output payload against the contract. Returns a
    list of problems (empty = valid)."""
    problems: list[str] = []
    if set(payload.keys()) != {"hours"}:
        problems.append(f"top-level keys are {sorted(payload.keys())}, want only 'hours'")
    hours = payload.get("hours", [])
    if len(hours) != 23:
        problems.append(f"expected 23 hourly rows, got {len(hours)}")
    seen: set[int] = set()
    for row in hours:
        if set(row.keys()) != {"hour", "q"}:
            problems.append(f"hour row keys are {sorted(row.keys())}, want hour+q")
            continue
        hour = row["hour"]
        if hour in seen:
            problems.append(f"hour {hour} appears twice")
        seen.add(hour)
        if not 2 <= hour <= 24:
            problems.append(f"hour {hour} outside 2..24")
        q = row["q"]
        if len(q) != 5:
            problems.append(f"hour {hour}: {len(q)} quantiles, want 5")
            continue
        for value in q:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f"hour {hour}: quantile {value!r} is not a number")
            elif not math.isfinite(value) or value <= 0 or value > MAX_QUANTILE:
                problems.append(f"hour {hour}: quantile {value!r} out of range")
        if all(isinstance(v, (int, float)) for v in q):
            if any(q[i] < q[i - 1] for i in range(1, 5)):
                problems.append(f"hour {hour}: quantiles decrease")
    if seen != set(range(2, 25)):
        problems.append(f"hours present are {sorted(seen)}, want 2..24")
    return problems


def run_self_test() -> int:
    """Determinism + schema self-test on a synthetic case. Returns the
    process exit code. Needs no case files."""
    failures: list[str] = []

    def fake_comparable(name: str, day: str, hour1: float,
                        growth: list[float]) -> dict:
        """A comparable whose release-day hours follow `growth` ratios."""
        start = parse_ts(day)
        hourly = [{"from": (start + timedelta(hours=i)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"), "viewers": hour1 * growth[i],
            "channels": 10} for i in range(24)]
        return {"name": name, "day_start": day, "hourly": hourly,
                "unlock": day, "platforms": [], "source": "synthetic"}

    # 12 comparables, all growing linearly from hour 1 (ratio 1 + 0.05*i).
    growth = [1.0 + 0.05 * i for i in range(24)]
    comparables = [fake_comparable(f"game-{i:02d}", "2026-01-01T00:00:00Z",
                                    100_000 + 1_000 * i, growth)
                   for i in range(12)]
    case = {
        "id": "self-test",
        "known": [{"hour": 1, "from": "2026-01-01T00:00:00Z",
                   "until": "2026-01-01T01:00:00Z", "viewers": 100_000,
                   "channels": 500, "reads": 60}],
        "forecast": [{"hour": h,
                      "from": f"2026-01-01T{h - 1:02d}:00:00Z",
                      "until": f"2026-01-01T{h:02d}:00:00Z"}
                     for h in range(2, 25)],
        "comparables": comparables,
        "history": [], "history_hourly": [],
    }

    first = forecast_case(case, "self-test")
    failures.extend(validate_output(first))

    # 1. Determinism: two independent runs must be byte-identical.
    blob1 = json.dumps(first, separators=(",", ":")) + "\n"
    blob2 = json.dumps(forecast_case(case, "self-test"),
                       separators=(",", ":")) + "\n"
    if blob1 != blob2:
        failures.append("forecast is not deterministic across runs")

    # 2. The median must track the comparables' growth (hour 20 ~1.95x).
    row20 = next(r for r in first["hours"] if r["hour"] == 20)
    if not 180_000 <= row20["q"][2] <= 210_000:
        failures.append(f"hour-20 median {row20['q'][2]} outside 180k..210k")

    # 3. Sparse comparables fall back without crashing (1 comparable).
    sparse = dict(case, comparables=comparables[:1])
    fallback = forecast_case(sparse, "self-test-sparse")
    failures.extend(validate_output(fallback))

    # 4. No comparables at all still yields a valid forecast.
    empty = dict(case, comparables=[])
    failures.extend(validate_output(forecast_case(empty, "self-test-empty")))

    # 5. A missing hour-1 print is an error, not a silent guess.
    try:
        forecast_case(dict(case, known=[]), "self-test-no-known")
        failures.append("missing hour-1 print was accepted")
    except ValueError:
        pass

    if failures:
        print("SELF-TEST FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("SELF-TEST PASSED: 23 rows x 5 quantiles, ordered, in range, "
          "deterministic, median tracks comparables, fallbacks valid.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forecast GTA VI launch-day Twitch viewers, hour by hour "
                    "(hours 2-24, five quantiles each).")
    parser.add_argument("--self-test", action="store_true",
                        help="Run determinism/schema self-tests and exit.")
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_test()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    inputs = sorted(INPUT_DIR.glob("*.in"))
    if not inputs:
        print(f"no *.in case files in {INPUT_DIR}", file=sys.stderr)
        return 2
    for path in inputs:
        case = json.loads(path.read_text(encoding="utf-8"))
        payload = forecast_case(case, path.name)
        problems = validate_output(payload)
        if problems:
            print(f"INVALID FORECAST for {path.name}:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 2
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n",
                            encoding="utf-8")
        print(f"{path.name} -> {out_path} "
              f"({len(payload['hours'])} rows, "
              f"{out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
