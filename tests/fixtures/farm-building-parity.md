# Farm building activity parity

Extracted with `tools/extract_building_capture.py` from actual recordings. Values
are decoded stream nodes; no production states are synthesized. The projection
keeps completed buildings, raw queue and MakeObjectAction/MakeTechAction fields,
player attributes, owner master type/class and living villagers at each sample.
The immutable node pool only deduplicates equal values.

| Capture | Recording SHA-256 | Samples |
|---|---|---:|
| Monoz moykyzcd4ivqs, first 800 s | `500664460c3b678f963839e4c9a918502dcda7430d1bb8cc122292164aaaa573` | 1600 |
| Monoz mqbf7pgwd76jh, first 800 s | `9897d70c627df29217869b748020cff7ec7c48fa3b41fa924ecb37bc437cab36` | 1600 |
| Dan Nov 11, fresh headless farm capture | `923386772a016c129f7ea08a3e19e0d6cded5d6a3fcde49428a1c30b3103734d` | 7019 |

The paired desktop projection already exists as
`dan-nov11-building-panels.json.gz`, from recording SHA-256
`232dcd37eaf72b66acb1332b456894957b307a77e85ce46644df26a21e16877a`.
Both full Dan recordings are separate game captures of the same original replay;
see the hub's `evidence/viewer-parity/recordings/conversion.json` for the genuine
farm invocation and `frame-comparison.json` for the comparison of all 7019 frames.

The tests pin Monoz's idle and continuous last minute at 12:07, compare Life,
last-minute and Fight scopes for TC 9129 and two Barracks, and retain Dan's 210 s
growth-phase idle. The tolerance is 1.5 seconds, covering the capture resolution;
these particular paired samples agree exactly. This is a recorded integration
regression, so CI does not need Steam or start a real game.

A fresh capture can be regenerated using `uv run farm/farm.py convert` in the hub
with its own `XDG_CACHE_HOME`, then re-extracted alongside the original desktop
capture. Never overwrite the source recordings to create these fixtures.
