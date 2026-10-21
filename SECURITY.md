# Security policy

## Reporting a vulnerability

Please report security problems privately through
[GitHub's private vulnerability reporting](https://github.com/dkapellusch/vantage/security/advisories/new).
Please don't open a public issue. You can expect a first
reply within a week.

## Scope

Vantage runs a local web server. By default it listens on `127.0.0.1` only; anything that lets a web
page or another machine read files, run commands, or reach the game's API through Vantage is in
scope. Binding to another address with `--host` exposes Vantage to that network: only do so on
networks you trust.

Never share certificate files (`*.pem`, `*.key`) in issues, pull requests or recordings.
