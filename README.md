# gta6-twitch-ccu-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Zallan03/gta6-twitch-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Zallan03/gta6-twitch-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Hour-by-hour forecast of GTA VI's launch-day Twitch concurrent viewers: a deterministic, stdlib-only Python model that reads the case file (`/input/<id>.in`), anchors on hour 1's print, and forecasts hours 2–24 as five quantiles each (0.05/0.25/0.5/0.75/0.95) from the case's own comparable launches.

## Run it

```sh
python3 main.py --self-test
mkdir -p out && MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

This writes `<id>.out` per case (23 rows: hour, five quantiles). See `METHODOLOGY.md` for the model, its assumptions, and its limitations.

---

<sub>Entered on [make.fun](https://make.fun/?ref=em9qff40&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
