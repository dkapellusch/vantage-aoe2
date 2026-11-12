# Selected-building idle regression fixture

`dan-nov11-building-panels.json.gz` retains 7,019 authentic decoded samples from
`live-20261111-193447-6.vrec` (SHA-256
`232dcd37eaf72b66acb1332b456894957b307a77e85ce46644df26a21e16877a`).
It extends the existing TC growth fixture with **all** buildings, including empty
ones and their foundations. Queues, research, completion, population and living
villagers are source fields, not generated activity labels. Node interning keeps
the fixture small; the full replay and artwork are not included.

`test_building_panel_activity.py` runs the actual BuildingHistory decoder and the
unit/group queries consumed by the selected-building panel:

- TC 9129: 955.7 seconds idle, 1912.5 producing, 570 researching, 69 housed,
  1.5 population-blocked, over a 3508.672-second observed lifetime. Its own
  growth-window idle is **34.0 seconds**; the player's overlapping-TC union is
  **210 seconds**, a different metric. Life shows the whole building lifetime.
- Last 60 seconds: 60 idle. Fight interval 20:00–25:00: 8.5 idle and 291.5 work.
- Barracks 21721: working immediately at completion (43:14.083); zero idle
  through 43:50.055. Barracks 11959 also trains continuously from
  53:35.071–54:46.055, with zero idle inside that interval.
- Barracks 11959 before its first queue: completed 8:07.557, first production
  9:37.561. Its unused completed age is 90.004 seconds, all idle. Its 51.997
  seconds as a foundation are construction, not idle.

Separate synthetic controls protect destroyed-building scope boundaries and
make building queue history authoritative over a generic unit-task fallback.
All production/research building IDs share queue-handoff controls. Housed time
is excluded from idle and is visible separately in the inspector.

Reproduce:

```sh
uv run python tools/extract_tc_growth_fixture.py \
  ~/.local/share/vantage/recordings/live-20261111-193447-6.vrec \
  --all-buildings --output tests/fixtures/dan-nov11-building-panels.json.gz
uv run pytest -q tests/test_building_panel_activity.py tests/test_building_activity.py
```
