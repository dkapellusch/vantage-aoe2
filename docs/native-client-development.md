# Experimental native conversion client

The recording-only server has a development client for a local native replay
worker. It can convert, poll, cancel and open an accepted recording without
game discovery or game API probing. Open `/native` from the viewer's navigation.

```sh
vantage serve --recording-only \
  --native-worker /absolute/path/to/client.json \
  --native-worker-sha256 EXPECTED_DESCRIPTOR_SHA256 \
  --experimental-native
```

The descriptor must have kind `vantage_native_worker_client`, version 1, an
explicit command, pinned command input files and a pinned version 1 engine
registry. Only explicitly experimental V32 engines are currently accepted.
The registry selects exact replay families; unknown builds fail before a
worker starts. Worker commands implement the `native_engine_convert` file-result
contract. The client validates output identities and original admission
receipts before exposing an accepted recording.

One owned worker runs at a time. It inherits a single logical CPU and nice 19;
cancellation controls only that worker's process group and suppresses late
results. Progress is indeterminate and reports elapsed time. Complete native
game end and recording EOF previews remain distinct.

## Import a retained engine

The development importer takes exact local package/runtime identities, a pinned
registry and a pinned ticket identifying three reviewed bootstrap source files:
`native_conversion`, `native_engine_package` and `native_engine_runtime`.

```sh
python -m vantage.native_bundle import \
  --package /local/engine --package-id PACKAGE_CONTENT_ID \
  --capsule /local/runtime --capsule-id RUNTIME_CONTENT_ID \
  --registry /local/registry.json --registry-sha256 REGISTRY_SHA256 \
  --bootstrap-sources /local/bootstrap-sources.json --bootstrap-sha256 TICKET_SHA256 \
  --destination /local/imported-engine
```

The source ticket has kind `vantage_native_bootstrap_sources`, version 1 and a
`modules` object mapping those three names to exact `path`, `bytes` and `sha256`
identities. Import copies and verifies all declared engine/runtime bytes,
checks the registry against the package, and writes `client.json` plus an import
receipt. Use the descriptor SHA256 from that receipt with `vantage serve`.
An optional `--link` shares immutable payload inodes on the same filesystem;
the default makes private copies. Failed imports remain separate from later
attempts and do not publish a usable client descriptor.

The imported controller stages raw replay/registry bytes by hash inside the
owned cache. Its host bootstrap uses stdlib and the three pinned modules.
Compiler, worker and Wine execute in the verified captured filesystem with an
empty namespace root. Accepted results are returned only after full captured
filesystem postverification. The controller preserves the engine's original
checksum and terminal admission; it does not confer supported status.

The current captured evidence contains 56 passing tests using authored Python
fixtures, including import integrity, repeated identical bootstrap aliases,
conflict rejection, staging, invalid worker results, cancellation,
recording-only HTTP workflow, untracked bootstrap code, Python startup isolation,
staging races, cancellation during postverification and owned-child cleanup.
The reviewed bootstrap executes bounded verified source bytes directly and
rejects untracked packages, extensions and bytecode caches.

A real retained package/runtime import passes, as does full-match cache
re-admission through the standalone client. A fresh-cache short conversion also
passes with host research and Steam roots hidden, a private network and the
game API unreachable. Its 513 serialized frames and all eight native streams
match the retained baseline. The input descriptor's pathname-dependent hash is
bound separately to the original source plan; replay/save bytes and every
non-path descriptor field agree. The output is explicitly an EOF preview.

Browser checks of `/native` now cover no imported engine, experimental opt-in,
progress, cancellation, worker failure and recording/preview opening with
authored workers. A separate real imported-engine browser run revalidates the
existing 513-frame preview through original admission/capsule checks, opens it,
loads the complete timeline and verifies pause, seek, resume, speed and the
visible incomplete-recording message. Host game/research roots are hidden and
the game API is unreachable. That browser run reuses the accepted native job;
it does not establish a fresh browser-driven simulation.

These checks do not qualify a new native engine or complete the release drill.
Fresh browser-driven native conversion, independent complete matches from two
qualified builds, actual update rehearsal and rollback remain required.
