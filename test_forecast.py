#!/usr/bin/env python3
"""Tests for main.py (stdlib unittest only). Run: python3 -m unittest test_forecast.py -v"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as forecast


def fake_case(n_comparables=12, hour1=100_000):
    """A synthetic case: comparables growing linearly from hour 1."""
    growth = [1.0 + 0.05 * i for i in range(24)]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    comparables = []
    for i in range(n_comparables):
        hourly = [{"from": (start + timedelta(hours=h)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"), "viewers": (hour1 + 1_000 * i) * growth[h],
            "channels": 10} for h in range(24)]
        comparables.append({"name": f"game-{i:02d}",
                            "day_start": "2026-01-01T00:00:00Z",
                            "hourly": hourly, "unlock": "2026-01-01T00:00:00Z",
                            "platforms": [], "source": "synthetic"})
    return {
        "id": "test",
        "known": [{"hour": 1, "from": "2026-01-01T00:00:00Z",
                   "until": "2026-01-01T01:00:00Z", "viewers": hour1,
                   "channels": 500, "reads": 60}],
        "forecast": [{"hour": h,
                      "from": f"2026-01-01T{h - 1:02d}:00:00Z",
                      "until": f"2026-01-01T{h:02d}:00:00Z"}
                     for h in range(2, 25)],
        "comparables": comparables,
        "history": [], "history_hourly": [],
    }


class TestForecast(unittest.TestCase):
    def test_23_rows_hours_2_to_24(self):
        payload = forecast.forecast_case(fake_case(), "test")
        self.assertEqual(len(payload["hours"]), 23)
        self.assertEqual([r["hour"] for r in payload["hours"]],
                         list(range(2, 25)))

    def test_five_quantiles_ordered_in_range(self):
        payload = forecast.forecast_case(fake_case(), "test")
        for row in payload["hours"]:
            q = row["q"]
            self.assertEqual(len(q), 5)
            for value in q:
                self.assertGreater(value, 0)
                self.assertLessEqual(value, 1_000_000_000)
            self.assertEqual(q, sorted(q))

    def test_output_validates_clean(self):
        self.assertEqual(
            forecast.validate_output(forecast.forecast_case(fake_case(), "test")),
            [])

    def test_median_tracks_comparables(self):
        payload = forecast.forecast_case(fake_case(), "test")
        row20 = next(r for r in payload["hours"] if r["hour"] == 20)
        # Comparables grow 1 + 0.05*i: hour 20 is 1.95x hour 1.
        self.assertGreaterEqual(row20["q"][2], 180_000)
        self.assertLessEqual(row20["q"][2], 210_000)

    def test_deterministic_bytes(self):
        case = fake_case()
        a = json.dumps(forecast.forecast_case(case, "test"),
                       separators=(",", ":")) + "\n"
        b = json.dumps(forecast.forecast_case(case, "test"),
                       separators=(",", ":")) + "\n"
        self.assertEqual(a, b)

    def test_fallback_valid_with_no_comparables(self):
        case = fake_case(n_comparables=0)
        payload = forecast.forecast_case(case, "test-empty")
        self.assertEqual(forecast.validate_output(payload), [])

    def test_missing_hour1_raises(self):
        case = fake_case()
        case["known"] = []
        with self.assertRaises(ValueError):
            forecast.forecast_case(case, "test-no-known")

    def test_validate_output_catches_bad_shapes(self):
        good = forecast.forecast_case(fake_case(), "test")
        bad = dict(good, hours=good["hours"][:10])
        self.assertTrue(forecast.validate_output(bad))
        bad2 = json.loads(json.dumps(good))
        bad2["hours"][0]["q"] = [5, 4, 3, 2, 1]
        self.assertTrue(forecast.validate_output(bad2))

    def test_quantile_helper(self):
        self.assertEqual(forecast.quantile([1.0, 2.0, 3.0, 4.0], 0.5), 2.5)
        self.assertEqual(forecast.quantile([10.0], 0.95), 10.0)

    def test_cli_writes_out_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = Path(tmp) / "in"
            out_dir = Path(tmp) / "out"
            in_dir.mkdir()
            (in_dir / "t00.in").write_text(json.dumps(fake_case()))
            env = dict(os.environ, MAKEFUN_INPUT_DIR=str(in_dir),
                       MAKEFUN_OUTPUT_DIR=str(out_dir))
            result = subprocess.run(
                [sys.executable, "main.py"], cwd=Path(__file__).resolve().parent,
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads((out_dir / "t00.out").read_text())
            self.assertEqual(forecast.validate_output(payload), [])
            # Second run: byte-identical output.
            first_bytes = (out_dir / "t00.out").read_bytes()
            result = subprocess.run(
                [sys.executable, "main.py"], cwd=Path(__file__).resolve().parent,
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(first_bytes, (out_dir / "t00.out").read_bytes())

    def test_self_test_passes(self):
        result = subprocess.run(
            [sys.executable, "main.py", "--self-test"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SELF-TEST PASSED", result.stdout)


if __name__ == "__main__":
    unittest.main()
