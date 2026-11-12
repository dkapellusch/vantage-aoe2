# Third-party runtime dependencies

Vantage's own code is MIT-licensed (see [LICENSE](LICENSE)). Dependencies retain
their own licenses and are installed as separate, replaceable Python packages.

- **genieutils-py 0.1.2** — **GNU LGPL version 3**, not MIT. Reads the user's
  installed `empires2_x2_p1.dat`; the library is used unmodified and pinned in
  `pyproject.toml` / `uv.lock`. Game executables, complete dat files, art and
  library code are not copied
  into Vantage. Tests contain a small extract of factual effect/availability
  records; production reads the user’s installed data. [Versioned source](https://github.com/SiegeEngineers/genieutils-py/tree/e1ff9db0b11442587b96f1a65ffdb972cff2d9fc),
  [LGPL license](https://github.com/SiegeEngineers/genieutils-py/blob/e1ff9db0b11442587b96f1a65ffdb972cff2d9fc/LICENSE),
  [GNU GPL v3 incorporated by LGPL](https://www.gnu.org/licenses/gpl-3.0.html).
  The ordinary Python import mechanism permits using an interface-compatible
  modified library; users can install that package into their environment.
- **grpcio** — Apache License 2.0. [Source and license](https://github.com/grpc/grpc).
- **protobuf** — BSD 3-Clause. [Source and license](https://github.com/protocolbuffers/protobuf).

`genieutils-py`'s source release and wheel are available on
[PyPI](https://pypi.org/project/genieutils-py/0.1.2/). Its upstream library license
must also accompany any distribution that bundles that dependency. Vantage's
source/wheel installs it through package metadata rather than vendoring it.
