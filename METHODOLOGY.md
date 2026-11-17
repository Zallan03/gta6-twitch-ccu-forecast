# Methodology — GTA VI launch-day Twitch CCV forecast

## What the entry predicts

For each of hours 2–24 of launch day (UTC), five quantiles (levels 0.05,
0.25, 0.5, 0.75, 0.95) of the Twitch category "Grand Theft Auto VI"
concurrent-viewer count. The grader runs `python3 -P -s /bot/main.py`
once per case: the program reads every `<id>.in` in `$MAKEFUN_INPUT_DIR`
(else `/input/`) — one JSON object, schema `makefun/twitch-ccu-case/v1`,
with hour 1's print in `known`, the 23 rows to forecast in `forecast`,
and the past launches' hourly counts in `comparables` — and writes
`<id>.out` to `$MAKEFUN_OUTPUT_DIR` (else `/output/`):
`{"hours": [{"hour": h, "q": [q05, q25, q50, q75, q95]}, ...]}`.

Score: mean pinball loss on the log scale over every scored hour and
quantile. A prize needs a loss strictly below the best house entry's
(the house baseline — persistence with a widening spread — scores about
0.387 on the practice cases).

## Model: comparable-launch empirical quantiles

The forecast is anchored on the case's own hour-1 print `p1` (a print
below 1 counts as 1). For each forecast hour `h` (2–24):

1. **Shape.** Take every comparable launch that has a viewer count for
   both its release-day hour 1 and hour `h`, and compute the log-ratio
   `ln(viewers_h / viewers_1)`. The median of those log-ratios is the
   hour's typical log growth over hour 1. Medians are robust to the odd
   launch whose unlock hour falls outside the UTC day, and the
   comparables are the launches the case itself ships, so nothing is
   tuned on the case being forecast.
2. **Spread.** The five quantiles are the EMPIRICAL quantiles of the same
   log-ratios at the scored levels (linear interpolation): `q_tau(h) =
   p1 * exp(Q_tau)`, rounded to 2 decimals (half up, like the house
   baseline's starter). A pinball loss is a proper scoring rule for
   quantiles, so the forecast scores best by writing the quantiles it
   really believes; the empirical quantiles are the calibrated choice for
   a skewed distribution, where a symmetric log-normal spread would
   overstate both tails.
3. **Fallback.** When fewer than 8 comparables carry both hours (sparse
   sampling leaves some launches without a point for an hour), fall back
   to a fixed launch-day profile shape (a midnight launch rush, an
   overnight trough, a climb to a 19:00 UTC peak), with the house
   baseline's widening spread `0.15 * sqrt(h - 1)`.

No fitted parameters, no tuning on the practice answers: the shape and
spread come from the case file itself at run time.

## Local validation

- `python3 main.py --self-test` — determinism + schema checks on a
  synthetic case (no case files needed).
- `python3 -m unittest test_forecast.py -v` — unit tests, including a
  full CLI run on a synthetic case through `MAKEFUN_INPUT_DIR` /
  `MAKEFUN_OUTPUT_DIR` with a byte-identical second run.
- Practice cases (kit `input/p00.in`–`p03.in`): all four produce valid
  outputs (23 rows × 5 quantiles, ordered, in range, ≤ 65,536 bytes),
  byte-identical across two runs, ~0.4 s per case (cap: 8 s).
- Leave-one-out check on the 38 comparables' own launch days (each
  launch forecast from the other 37, scored against its real hourly
  prints): mean pinball loss **0.714** for this model, vs **0.798** for
  the median + log-normal-spread variant and **0.930** for the house
  baseline on the same launches. The kit's sealed scorer stays on the
  server (`grade-local` refuses this kit), so the practice loss itself
  can only be read after submission.
- The first build of this entry assumed the wrong I/O contract (a fixed
  24-row CSV/JSON forecast, no case file). The kit's `RULES.txt` showed
  the real contract (`/input/<id>.in` → `/output/<id>.out`, 23 rows × 5
  quantiles); `main.py` was rewritten to it and the stale
  `forecast.csv` / `forecast.json` / `data/anchors.csv` removed.

## Determinism and dependencies

- Python 3 standard library only. No network, no wall clock, no
  randomness, no environment reads except `MAKEFUN_INPUT_DIR` /
  `MAKEFUN_OUTPUT_DIR`.
- The forecast is a pure function of the case file. Two runs on the same
  case are byte-identical — verified by `--self-test`, by the unit tests,
  and by running the practice cases twice and diffing.

## Assumptions and limitations (read before trusting the numbers)

- The shape is a median over past launches, so it cannot know GTA VI's
  own launch-day curve: a single mega-streamer event, a platform outage,
  or a regional unlock pattern unlike any past launch could move the
  true counts outside the bands.
- The empirical outer quantiles come from ~37 launches, so the 5th/95th
  percentiles are noisy by construction; they are the honest calibrated
  choice for pinball loss, not a claim of precision.
- Launches whose hour 1 (00:00–01:00 UTC) was still pre-launch sit in
  the reference set with very large log-ratios; the median is robust to
  them, and filtering them out scored worse in leave-one-out validation,
  so they stay in.
- The model does not use live Twitch data, streamer schedules, or the
  case's `streams` / `categories_hourly` (null in the practice cases).

## Reproduce

```sh
python3 main.py --self-test   # determinism + schema checks
python3 -m unittest test_forecast.py -v
mkdir -p out && MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```
