# The game's spectator stream

This page describes what Age of Empires II: DE sends to a spectator client and how Vantage decodes it. The reference implementations are `src/vantage/live.py` (transport), `src/vantage/patch.py` (the patch interpreter), `src/vantage/schema.py` with `cade_schema.json` (the schema), and `src/vantage/rpc/cade.proto` (the messages).

It covers message shapes, and model and field numbers, names and widths, and how Vantage's decoder reads them.

## Transport

- The game runs a gRPC server, service `cade_api.rpc.CadeRemote`, on `127.0.0.1:4341` while it runs.
- It requires **mutual TLS**. The server certificate is issued to the name `ca-game-api`, so the client must ask for that name (TLS SNI and HTTP/2 `:authority`) whatever address it connects to. The client must present a certificate issued by the authority the game trusts. Vantage loads these from its certificate folder (`certs.py`) and does not ship them.
- The server has no reflection, so Vantage calls methods by their wire path (`/cade_api.rpc.CadeRemote/<Method>`) using the messages in `rpc/cade.proto`. That file's package is renamed to `vantage.cade`. Its field names are lower-case, as the game's own generated code has them, which makes no difference on the wire.
- **One stream per connection.** A second stream on a connection that already carried one fails (`TSI_DATA_CORRUPTED`). Vantage opens a private connection for each stream (`grpc.use_local_subchannel_pool`): one for `Frames`, one for `Oracle`, and short-lived ones for commands sent between streams.
- **Flow control.** If grpcio is allowed to grow its HTTP/2 window freely, the game writes a large snapshot (about 18 MB for a six-player game) in one burst, and its TLS layer corrupts records. A bounded window prevents this: Vantage sets `grpc.http2.bdp_probe=0` and `grpc.http2.lookahead_bytes=1 MiB`. The receive limit is raised to 128 MiB.

### Methods

| Method | Kind | Use |
|---|---|---|
| `Info` | unary | Game build, API version, install folder, profile folder, enabled mods, language, selected game |
| `Frames` | server stream | The world: a snapshot, then deltas |
| `Oracle` | bidirectional stream | Status pushed by the game: pause (and who paused), screen, window, spectator lobby, game type and state, current replay, chat, modals |
| `LoadGame` | unary | Play a replay (local or cloud), spectate a lobby, restart as replay, cancel. Has a `confirm` flag |
| `SetDesiredGame` | unary | Switch between Age of Empires II and Return of Rome |
| `Pause`, `SetGameSpeed`, `SetFogOfWar`, `SetPerspective` | unary | Spectator controls |
| `ChangeWindowState`, `ChangeScreen`, `AccessFlag`, `StartScenario` | unary | Window and menu control |

`Info.apiversion` is the API version. Vantage understands versions up to 22, and reports a newer game as needing an update.

`LoadGame` and `SetDesiredGame` answer `FAILED_PLAYING_NEED_CONFIRM` when they would leave a game in progress. A second request with `confirm=true` goes ahead. Vantage only sends that after the user agrees. A game that refuses the API to a player in the match fails the call with `PERMISSION_DENIED` and detail `PLAYER_NO_CAPTUREAGE`.

`Info.selectedgame` / `SetDesiredGame` use 1 for Return of Rome (`EMPIRES1`, mode path `modes\Pompeii\`) and 2 for Age of Empires II (`EMPIRES2`).

### The Frames request

```
FramesRequest {
  desiredresolutions:          [{key: category, gametimeresolution: ms}]
  disablecommands:             bool
  disableparticles:            bool
  particledefinitionwhitelist: [string]
  disableparticleculling:      bool
  processattacknotificationsforallplayers: bool
  resolvestickyunitlists:      bool
}
```

- **Resolution.** Category 0 (`TIME_STEP`) sets the game time per frame. Vantage uses 100 ms normally and 500 ms for fast replay. Other categories (1 low priority, 2 sleeping units, 3 particles, …) can be made coarser to spare the game work. Patches are cumulative, so a coarser resolution skips intermediate states but loses nothing.
- **Particles must be whitelisted by name.** With particles enabled and an empty whitelist, the game streams particle slots with no content. Vantage sends the names of the particle definitions in the installed game (`resources/_common/particles/*.json`), or a subset of them for fast replay. Turning culling off (`disableparticleculling`) makes the stream fail.
- The game reads the request once per stream. To change it, Vantage reopens the stream, and the new stream starts with a full snapshot.

### Frames

The stream delivers `FrameSequence { frame[], sendingworldtime, numberofframesqueued }`. Each `Frame` has:

| Field | Meaning |
|---|---|
| `time` | Game time, ms |
| `patch` | Forward patch: the changes since the previous frame (or the whole world) |
| `reversepatch` | Reverse patch (in practice the game sends none) |
| `event[]` | Game events, one of 11 kinds: `entitykilled`, `markettransaction`, `tribute`, `playerchat`, `combatnotificationsound`, `damage`, `monkconversion`, `notificationtraindone`, `notificationresearchdone`, `notificationfarmorfishtrapdied`, `notificationwonder` |
| `command[]` | Player commands issued in this step (used for APM, tribute, treason and more) |
| `timestepsskipped`, `skippedtimesteps` | Steps the game skipped (shown as hatched marks on the time bar) |
| `metrics[]` | The game's own timing measurements |

## The state tree

The world is a tree of typed **objects**. Each object has a **model** (its type), and holds **fields** numbered from 0 within that model. The root is model 0 (`Root`), with `world` (model 1, `World`) and `gameOptions` (model 35).

Each field has a **kind**:

| Kind | Holds |
|---|---|
| `scalar` | One value of a fixed wire type |
| `object` | One child object (or nothing) |
| `map` | Child objects keyed by an `i32` |
| `array` | A list of child objects (slots may be empty) |
| `scalar_array` | A list of scalar values |

Scalar wire types: `Int8`, `UInt8`, `Boolean` (1 byte); `Int16`, `UInt16` (2); `Int32`, `UInt32`, `Float` (4); `Int64`, `UInt64`, `Double` (8); `String` (`u32` byte length, then UTF-8 bytes).

### The schema

`cade_schema.json` lists **51 models and 1,349 fields**:

```json
{"models": {
  "1": {"name": "World", "fields": {
    "0": {"name": "time", "kind": "scalar", "type": "UInt32"},
    "1": {"name": "entities", "kind": "map", "key": "Int32", "model": 9},
    "9": {"name": "mapTiles", "kind": "array", "key": "Int32", "model": 3, "contiguous_model": 3},
    "17": {"name": "unifiedVisibleMap", "kind": "scalar_array", "type": "UInt32"}
  }}
}}
```

`model` is the declared model of a container's elements. `contiguous_model` is the model a `RESIZE` fills new slots with. Without it, new slots are empty.

The models are:

`Root`, `World`, `ColorTable`, `MapTile`, `TerrainType`, `Player`, `Relation`, `VictoryPointEntry`, `PlayerAttributes`, `Entity`, `DoppleEntity`, `ActionEntity`, `CombatEntity`, `MissileEntity`, `BuildingEntity`, `ProductionQueueRecord`, `MasterEntity`, `MasterActionEntity`, `MasterCombatEntity`, `ArmorWeaponInfo`, `MasterMissileEntity`, `MasterBuildingEntity`, `Action`, `MakeObjectAction`, `MakeTechAction`, `GatherAction`, `HuntAction`, `ConvertAction`, `ActiveSprite`, `Sprite`, `DeltaSprite`, `Technology`, `TechnologyPrerequisite`, `AttributeValue`, `ResearchState`, `GameOptions`, `PlayerGameOptions`, `SoundEvent`, `SoundList`, `ParticleInstance`, `WonderAction`, `PackAction`, `UnpackAction`, `MakeAction`, `TerrainSpriteInfoList`, `TerrainSpriteInfo`, `UnitGroup`, `MasterMovingEntity`, `DamageSpriteInfo`, `Task`, `TreatyMode`.

Models extend one another: `Entity` → `ActionEntity` → `CombatEntity` → `BuildingEntity`, for example. A subtype's field table is a superset of its base's. A container declares a base model, but each element can be a more specific model. The concrete model of each element is carried in the stream (see `PUSH_CREATE_*` below), and it decides how wide that element's fields are.

## Patches

A patch is a sequence of **instructions** for a stack machine. The machine keeps a cursor on the current object, starting at the root, and a stack of the objects above it. All integers are little-endian.

### Instructions

| Op | Name | Operands | Effect |
|---|---|---|---|
| 1 | `POP` | | Return to the parent object |
| 2 | `ASSIGN_FIELD` | `fid:u8`, value | Set a scalar field |
| 3 | `PUSH_FIELD` | `fid:u8` | Descend into an existing object field |
| 4 | `PUSH_CREATE_FIELD` | `fid:u8`, `model:u8` | Replace an object field with a new, empty object of `model`, and descend into it |
| 5 | `RESET_FIELD` | `fid:u8` | Clear an object field |
| 6 | `ASSIGN_KEY` | `fid:u8`, `key:i32`, value | Set element `key` of a scalar array |
| 7 | `PUSH_KEY` | `fid:u8`, `key:i32` | Descend into an existing element of a map or array |
| 8 | `PUSH_CREATE_KEY` | `fid:u8`, `model:u8`, `key:i32` | Put a new object of `model` at `key` of a map or array, and descend into it |
| 9 | `RESET_KEY` | `fid:u8`, `key:i32` | Remove a map entry, or empty an array slot |
| 10 | `INSERT` | `fid:u8`, `index:i32`, value | Insert a value into a scalar array |
| 11 | `PUSH_CREATE_INSERT` | `fid:u8`, `model:u8`, `index:i32` | Insert a new object of `model` into an array, and descend into it |
| 12 | `REMOVE` | `fid:u8`, `index:i32` | Remove an element of an array or scalar array |
| 13 | `SWAP` | `fid:u8`, `index:i32`, `index:i32` | Swap two elements |
| 14 | `RESIZE` | `fid:u8`, `count:i32` | Truncate a sequence, or extend it with default values (`contiguous_model` objects, empty slots, or zero scalars) |

Each `value` is a scalar of the wire type that the **current object's model** gives for that field. **Widths are not in the stream.** The same field number can be a `u32` on one model and a `float` on another, so a decoder must know the concrete model of every object it is inside. It learns that from the `PUSH_CREATE_*` operands, and so a stream can only be decoded from a snapshot onwards.

Every `PUSH_*` is matched by a `POP`, and a well-formed patch ends back at the root. Nesting never exceeds 10 levels. A strict decoder rejects:

- an unknown opcode,
- a field the current model does not have,
- an opcode applied to a field of the wrong kind,
- an index out of range,
- a patch that ends inside an instruction or without closing every `PUSH`.

Any of these means the client is out of step with the game and must wait for the next snapshot.

### Snapshots and deltas

A patch whose first byte is `4` (`PUSH_CREATE_FIELD` on the root) is a **snapshot**: it builds the entire world from nothing. Every `Frames` stream begins with one. That is how a client resynchronises after a dropped connection, and why a recording must begin with one. Every later frame is a **delta**, typically a few kilobytes.

**Default values are omitted.** A snapshot only writes fields that are not zero, false or empty. A field that is absent therefore means 0. For example, `Entity.heldAttributeType` absent means food (type 0), and a building whose "built" flag is absent is still a foundation. Icon 0 and cost type 0 are real values, not "missing".

### Reverse patches

A reverse patch undoes a forward one, so a client could step backwards without re-simulating. It begins with a `0x00` marker byte and is read **from the end towards the start**. The opcode is the last byte, its operands come before it, and each multi-byte value (including a string's length, which follows its bytes) is read ending at the cursor. In practice the game sends no reverse patches. Vantage's decoder supports them, and its tests cover them, but Vantage keeps history as keyframes instead (see [architecture.md](architecture.md#keyframes-and-seeking)).

### Lenient decoding

For analysing captures that lack the initial snapshot, `Patcher(lenient=True)` creates placeholders for objects it has not seen. It narrows a placeholder's model to the most specific subtype that declares the fields being edited. This is a tool for analysis. A live view always decodes strictly.

## Reading the world

`world.py` gives names to the tree. Field ids are looked up by name in the schema, so a schema change surfaces as an error, not as silently wrong data. Some facts the interface depends on:

- **Resources** are `Player.attributes` (`PlayerAttributes`) fields 0–3: food, wood, stone, gold. Other attributes cover population, kills, relics and more.
- **Score.** `Player.victoryPointMap` holds the score's parts (military, economy, technology, society). They sum to the game's total score.
- **Visibility.** `World.unifiedVisibleMap` holds one `u32` per tile. Bit *k* is player *k*: the low 16 bits are "visible now", and the high 16 are "explored".
- **Entity state.** 2 is alive. 3 is gatherable remains (counted as present for Gaia only), 4 is dying and 5 a decaying corpse. Entities flagged `doppleFlag` are fog-of-war memories and are not real units.
- **Research.** `ResearchState` state 3 means researched. Progress of an active research comes from the building's `MakeTechAction`.
- **Resources left.** An object's `heldAttributeAmount` is what it still holds. Its master's first `attributesHeld` entry is the full amount.
- **Sprites.** `Entity.spriteList` (or the master's standing sprite) gives sprite ids, and `World.sprites[id]` names the sprite file. Buildings stream only a composite root sprite whose draw list adds the parts.
- **Which game.** `World.selectedGame` and `Info.selectedgame` tell Age of Empires II from Return of Rome.

## Events and the Oracle

Frame events carry what the world tree does not record directly: who killed whom, damage dealt, market trades, tributes, chat, conversions, and "unit trained" and "research done" notifications. Vantage stores them with each frame in recordings, as JSON objects `{"kind": <name>, ...fields}`.

The `Oracle` stream is opened with one `InfoRequest` prayer, after which the game pushes status changes:

| Message | Use |
|---|---|
| `gamepaused` | Pause state, and the player who paused |
| `currentscreenstate`, `currentwindowstate` | Which screen the game shows (for example, the spectator lobby); its window |
| `observerlobby`, `observerleave` | The spectator lobby: players, settings, match start and join times |
| `gametype`, `gamestate` | Single-player, multiplayer, replaying or spectating; creation, playing or done |
| `currentreplay`, `selectedgame` | The replay being played; AoE2 or Return of Rome |
| `gamechat` | Chat, including chat sent while the game is paused, when no frames flow |
| `currentmodal`, `modalclickresult`, `emptycurrentmodal` | The game's dialogs |

## Validation

Vantage's tests decode the committed fixture streams byte-exactly. The decoder has also decoded complete live captures of 3- and 6-player games, 40 to 80 minutes long, with no errors. Tests also build streams with a small patch encoder (`tests/helpers.py`) to cover every instruction, reverse patches and error cases.
