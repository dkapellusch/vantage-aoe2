# TC growth-window replay fixtures

`*-tc-growth.json.gz` contain decoded fields from the three actual recordings
below, with node interning (`{"$": index}` into `nodes`) to avoid repeating
unchanged villagers/masters thousands of times. No production queues, living
villagers, population fields, timing or activity classifications are invented.
The tests run `BuildingHistory.sample` on every original sample, then compare
growth and whole-game **elapsed union**, not summed TC-seconds.

| Source recording | Samples | Growth | Whole game | First 120 living villagers |
|---|---:|---:|---:|---:|
| `live-20261110-190527-3.vrec` (Shazama) | 5814 | 2:36 | 12:05 | 31:52.558 |
| `live-20261111-193447-6.vrec` (Shazama) | 7019 | 3:30 | 19:53 | 35:18.080 |
| `match.vrec` (Microsoft 519012025; VIT \| Hera) | 2738 | 0:43 | 0:43 | Not reached |

Each fixture retains its original recording header and SHA-256. The tests pin
those hashes, both numbers and exact cutoff milliseconds. The population limit
is 200 in these games and is reached later than the villager target (or never).
Synthetic controls separately pin an earlier population-limit cutoff, housing,
completion boundaries, overlapping TCs, a custom target, losses after cutoff,
and a TC completed after the window. Existing real queue fixtures pin housing,
research and subsecond handoffs independently of this window.

Reproduce with the installed viewer environment:

```sh
uv run python tools/extract_tc_growth_fixture.py \
  ~/.local/share/vantage/recordings/live-20261110-190527-3.vrec \
  --output tests/fixtures/dan-nov10-tc-growth.json.gz
uv run python tools/extract_tc_growth_fixture.py \
  ~/.local/share/vantage/recordings/live-20261111-193447-6.vrec \
  --output tests/fixtures/dan-nov11-tc-growth.json.gz
uv run python tools/extract_tc_growth_fixture.py \
  ~/.local/share/vantage-hub/matches/mly52vnwnqovw/match.vrec \
  --player 'VIT | Hera' --output tests/fixtures/hera-tc-growth.json.gz
uv run pytest -q tests/test_tc_growth.py
```

Extraction omits unrelated entity fields, positional/action detail and action
progress; only the raw queued/current identities are needed for idle. Retained
queued building heads preserve the player's housing classification. Dictionaries
are interned only when their complete retained fields are identical.
