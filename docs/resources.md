# Resource accounting

Every resource a player receives is counted once, in one of four places. The
names are the same in the Team board, the Pulse strip, Statistics, the review
panels and `metrics.js`.

| Name | What it is | Where it comes from |
|---|---|---|
| **Collected** | Gathered by villagers and fishing ships, including what they still carry | The game's `foodTotal`/`woodTotal`/`stoneTotal`/`goldTotal` counters, minus everything below that those counters also include, plus direct-farming food the counters lose (see "Counter drift") |
| **Bonus** | Civilization, technology and event grants | Listed by source in Statistics › Bonus resources. Includes the **Starting bonus** |
| **Trade** | Gold delivered by trade carts and cogs | `Player.tradeGoldReceived` |
| **Market**, **Tribute** | Exchanges with the market and other players | The game's market and tribute events |

**Starting resources** are the lobby's share of the stockpile at the start (200 food, 200 wood,
100 gold, 200 stone on Standard; a Nomad map adds the Town Center's cost). The civilization's
share is the **Starting bonus**, a Bonus row that can be negative (Chinese start with 200 food
and 50 wood less).

Collection rates (`/min`) are rates of Collected, so no grant, relic, trade or sale inflates them.
`recorded_collected` in the view keeps the game's raw counter.

## The identity

For each player and resource, at any time:

```
stockpile = Starting resources + Starting bonus
          + Collected + Bonus (after the start) + Trade
          + Market (received - paid) + Tribute (received - sent)
          + Refunds - Spent + Unexplained gain
```

`ResourceHistory` (`resource_review.py`) checks every frame. A stockpile change that the collected
counters, a credited grant, the market and tribute do not explain is:

- **Spent** when it is a decrease;
- a **Refund** when it is an increase and, within about a second, the player cancelled or
  dequeued something, lost a building or foundation, cancelled a research or resigned;
- otherwise an **Unexplained gain**, shown as its own row and never added to Bonus. It should be
  zero; a value means a source Vantage does not know.

Statistics › Bonus resources › **Stockpile accounts** shows these rows per player. They add up to
the stockpile.

`tools/reconcile_resources.py RECORDING.vrec` verifies the identity against a ground truth it
builds from the frames on its own, and prints the residual per player and resource.
`tests/test_resource_reconcile.py` does the same on windows of real recordings
(`tools/extract_resource_fixture.py` makes the fixtures).

## Sources

"Counter" says whether the game's collected counter includes the source. Sources inside the
counter are subtracted from Collected; the others are paid straight into the stockpile.
"Seen" names a real recording the behaviour was measured on; "dat" means it is read from the
installed game data and not yet seen in a recording.

### Starting stockpile

| Civilization | Amount | Trigger | How it is observed | Seen |
|---|---|---|---|---|
| Persians | +50 food, +50 wood | Start; on Nomad, the first Town Center | Executed dat tech 223 (starting attributes 91-94); on Nomad the stockpile receipt when it completes | regular start and Nomad |
| Aztecs | +50 gold | as Persians | dat tech 224 | dat |
| Sicilians | +100 stone | as Persians | dat tech 228 | dat |
| Tupi | +25 of each | as Persians | dat tech 1394 | dat |
| Chinese | -200 food, -50 wood | Start | dat tech 226 (the stream's starting attributes read 0) | mirror match |
| Huns | -100 wood | Start | dat tech 225 | dat |
| Maya | -50 food | Start | dat tech 227 | dat |
| Lithuanians | +100 food per Town Center | Start (the starting Town Center) and each new one | The Town Center's hidden annex (master 888, completion storage); kept at the start only when it agrees with the other players' stockpiles; later only with the receipt | dat |

Extra villagers, llamas, bushes and Mule Carts at the start are objects, not resources.

### Direct grants (not in the counter)

| Civilization | Source row | Amount | Trigger | How it is observed | Seen |
|---|---|---|---|---|---|
| Ethiopians | Age advancement | +100 food, +100 gold | Each age | Executed techs 587-589, 871 | dat |
| Dravidians | Age advancement | +200 wood | Each age | Executed techs 851-853, 872 | yes |
| Spanish | Technology research | +20 gold | Each research (not ages) | Research notifications | dat |
| Saxons | Camp construction | +35 food, +10 stone | Mill, Lumber or Mining Camp finished | Completion storage (flag 8) of the owner's master | yes |
| Wu | Production-building construction | +55 food | Military building or Dock finished | as Saxons | yes |
| Lithuanians | Town Center construction | +100 food | Town Center finished | Annex storage and the receipt | dat |

These are the only effects in the dat that add food, wood, stone or gold to a stockpile
(effect commands 1/6/11/16 on resources 0-3), together with the starting attributes above.

### Inside the counter (subtracted from Collected)

| Civilization | Source row | Mechanism | How it is observed |
|---|---|---|---|
| any | Relics | Relic gold; Aztecs +33%, Huns' Atheism, Burgundians also food | The game's relic income counter |
| Poles | Poles Folwark bonus food | Farms built next to a Folwark pay 10% of their food at once | Farm completions in range, confirmed by the food receipt |
| Malians, Spartans, Mapuche, Danes | Extra drop-off | +5% to +25% on a drop-off | The receipt beyond the carried load |
| Portuguese, Vietnamese (Paper Money), Burgundians (Vineyards), Poles, Athenians, Shu, Thracians, Puru, Varangians | Foraging wood, Paper Money, Burgundian Vineyards, Stone mining gold, Lumberjack food, Animal gathering, Stone mining food | A second resource generated while gathering | Carry-bonus tasks and receipts |
| Tatars (Keshik), Varangians | Keshik, Varangian Gold Generation | Gold while fighting | Receipts matched to attacking units and kills |
| Mapuche, Thracians, Danes, Tupi | Mounted-unit kills, Building loot, Fallen units | Rewards for kills, razings and losses | Receipts matched to kill events |
| Portuguese | Feitoria | Trickle of all four | Receipts with a finished Feitoria |
| Wei | Tuntian | Food from military units | Receipts with the tech |
| Gurjaras | Garrisoned livestock | Food from herdables in Mills | Receipts with garrisoned animals |
| Spartans | Peloponnesian League | Gold from Forts | Receipts with the tech |
| scenario units | Monument / Trade Workshop | Trickles | Receipts with the building |
| Bengalis and others | Trade bonus | Food, wood or stone from trade units | `Player.trade<Resource>Received` |
| any | Unattributed | Counter income with no proven source; stays in Collected | - |

Work-rate, carry-capacity, cost and "lasts longer" bonuses change how fast Collected grows; they
add no resource of their own. Statistics shows estimated savings and free units separately.

### Counter drift

Direct farming (Khmer, and anyone whose farmers need no drop-off) pays food every game tick. Once
`foodTotal` passes 8192 the game's 32-bit float counter drops part of those small amounts while
the stockpile keeps them (about 9 food per minute in the recording it was found in, starting the
second the counter crossed 8192). Vantage adds that food back to Collected (`uncounted`).

## Not covered yet

- Tribute and trade-cart income had no recording to measure against. Tribute is taken from its
  events and assigned to the counter or the stockpile by where the receipt appears.
- A grant paid in the same frame as a larger purchase cannot be seen in the stockpile. Rule-based
  grants (age-up, construction) are still credited; receipt-gated ones (Nomad starting bonus,
  Lithuanian Town Centers) would be missed for that frame and nothing else changes.
