# Vantage hub

A web app for uploading AoE2 DE replays (`.aoe2record`) and getting back the
match in the Vantage viewer, with a results table and charts. Linux only;
experimental. It sits in front of the [replay farm](../farm/README.md), which
does the converting, so it needs everything the farm needs.

```sh
python tools/farm/farm.py doctor     # what this machine can use
python tools/hub/hub.py serve        # http://localhost:8750
```

## What happens to an upload

1. **Checked.** The name must end in `.aoe2record`, the size be within
   `--max-mb` (64), and the header must parse. A replay from another game build
   than the installed one is refused at once with the reason: the game only
   plays replays of its own build. At most `--uploads-per-hour` (20) per client
   address.
2. **Stored** under a random, unlisted id (`m` and 12 letters). The same file
   uploaded again gets the match it already has. The page lists a visitor's own
   uploads from their browser's storage; there is no public list.
3. **Converted** by a game copy from the farm (`-j`, 2 at once). Copies start
   with the first upload, stay up for `--idle-seconds` (600) after the last and
   are started again when needed. From a cold start a 34-minute game was ready
   3 min 20 s after the upload; with a copy already up, about 2 minutes.
4. **Analysed** once: results, timings and the time series the charts draw.
5. **Watched.** Each open match gets a Vantage server of its own (at most
   `--viewers`, 4; the least recently used goes first; stopped after
   `--viewer-idle`, 900 s). The hub passes the browser's requests on to it.

## Why a match has its own host name

Vantage's interface asks its server for `/api/...`, `/static/...` and so on, one
match per server. So the hub gives each match a host name of its own,
`<id>.<the hub's host>`, and routes by it. On this machine that is
`<id>.localhost:8750`, which browsers resolve without any setup. On the
internet it means a wildcard DNS record and certificate:

```sh
python tools/hub/hub.py serve --host 0.0.0.0 --public-host replays.example.org --trust-proxy
```

with `*.replays.example.org` and `replays.example.org` pointing at the hub
(through a TLS-terminating proxy; `--trust-proxy` takes client addresses from
`X-Forwarded-For`). A side effect: the viewer's settings are kept per match.

## What a visitor can and cannot reach

- Through a match's host name only the viewer's read routes are passed on (the
  view at a time, events, series, sprites, icons, sounds, static files). The
  desktop server's other routes (opening files, the replay and recording lists,
  starting the game, settings) are refused, and every POST is answered
  "read-only", so bookmarks and review moments are not saved.
- The recording's path on the server is removed from the two answers that
  carry it.
- The game copy that reads an uploaded file runs in the farm's sandbox: no
  network, a read-only file system, the home folder hidden, and only its own
  instance folder writable.

## Before putting it on the internet

- **Game graphics.** By default viewers draw with the installed game's own
  sprites, icons and sounds, converted on demand, which means serving them to
  whoever opens a match. Vantage itself redistributes nothing from the game;
  whether a public site may is a decision for whoever runs it. `--no-game-art`
  makes viewers draw plain markers instead.
- **The game does the work.** Every conversion is the game playing a replay on
  this machine under the Steam account that is signed in. Check the game's and
  Steam's terms for a public service.
- **Nothing is ever deleted.** Uploads, recordings and analyses stay in
  `--data-dir` (`~/.local/share/vantage-hub`); a match is about 20 MB.
- **One process, Python's HTTP server.** Fine for a few people at once. Each
  open match costs about 300 MB and half a minute of loading.
