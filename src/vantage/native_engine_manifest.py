"""Read-only, bounded native-engine dependency audit.

This is a static inventory, never an executable loader or a compatibility claim.
It follows JSON pins and literal source references and records unresolved dynamic
access. In particular a verified top-level recipe is not dependency closure.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
from collections import Counter, deque
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "vantage_native_engine_inventory_v1"
_TEXT = {".json", ".py", ".h", ".hpp", ".cpp", ".c", ".inc", ".in", ".xs", ".sh"}
_HEX = re.compile(r"\b0x[0-9a-fA-F]{2,16}\b")
_INCLUDE = re.compile(r'^\s*#\s*include\s*(["<])([^">]+)[">]', re.M)
_LITERAL = re.compile(r'(?<![\w])(?:L|u8)?"([^"\n]{1,4096})"')
_ACCESS = re.compile(
    r"\b(fopen|freopen|CreateFile[A-Z]*|LoadLibrary[A-Z]*|open|read_bytes|read_text|read_json|load_library|CDLL|WinDLL|dlopen|glob|rglob)\s*\("
)
_PATH_KEY = re.compile(
    r"(?:path|root|file|image|library|template|source|target|encoder|directory|dir)$", re.I
)


def classify_dependency(path: str | Path, context: str = "") -> str:
    """Classify change impact, with conservative heuristic source roles."""
    name = str(path).lower()
    hint = (context + " " + name).lower()
    if any(
        x in hint
        for x in (
            "evidence",
            "audit",
            "verification",
            "receipt",
            "comparison",
            "result.json",
            "source_contracts",
        )
    ):
        return "verification"
    if any(
        x in hint
        for x in (
            "compiler",
            "python_target",
            "system.",
            "wine",
            "bwrap",
            "xvfb",
            "xauth",
            "/usr/",
            "site-packages",
        )
    ):
        return "runtime_toolchain"
    if any(x in hint for x in ("profile", "config")) and Path(path).suffix == ".json":
        return "recipe"
    if any(
        x in hint for x in ("private-image", "owned-image", "unpack", "protection", ".exe", ".dll")
    ):
        return "native_image_or_derivation"
    if any(
        x in hint
        for x in (
            "localization",
            "strings/",
            "/web/",
            "sprite",
            "graphics",
            "audio",
            "language",
            "presentation",
            "colorcorrection",
        )
    ):
        return "presentation"
    if any(x in hint for x in ("encoder", "codec", "convert.py", "timeline.py")):
        return "encoder"
    if any(x in hint for x in ("resources/", ".dat", ".xs", "asset", "terrain")):
        return "simulation_data"
    if Path(path).suffix in {".cpp", ".c", ".h", ".hpp", ".inc", ".in", ".py"}:
        return "adapter_source"
    return "unclassified"


def _sha_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def content_identity(files: list[dict[Any, Any]]) -> str:
    """Digest a multiset of logical names, roles and bytes, excluding local paths.

    JSON recipe bytes themselves contain roots. Their normalized content digest
    is supplied by the inspector; non-JSON contents retain their actual digest.
    The identity is an inventory identity, not an admission or execution key.
    """
    rows = [
        {
            "name": row["logical_name"],
            "roles": sorted(row["roles"]),
            "bytes": row.get("identity_bytes", row.get("bytes")),
            "sha256": row.get("normalized_sha256", row.get("sha256")),
            "status": row["status"],
        }
        for row in files
    ]
    return _sha_json(sorted(rows, key=lambda row: json.dumps(row, sort_keys=True)))


def _normalize_json(value: Any) -> Any:
    if isinstance(value, dict):
        # A pin's absolute path and the JSON file size/digest change when moved.
        if {"path", "bytes", "sha256"} <= value.keys():
            return {
                "logical_file": Path(value["path"]).name,
                **{
                    k: _normalize_json(v)
                    for k, v in value.items()
                    if k not in {"path", "bytes", "sha256"}
                },
            }
        return {
            k: (
                {"local_root": True}
                if k.endswith("root") and isinstance(v, str) and v.startswith("/")
                else _normalize_json(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_normalize_json(v) for v in value]
    if isinstance(value, str) and (value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value)):
        return {"local_path_basename": Path(value.replace("\\", "/")).name}
    return value


def inspect_engine_profiles(
    source_profile: Path,
    runtime_profile: Path,
    encoder_config: Path,
    *,
    replay: Path | None = None,
    max_files: int = 20000,
    max_total_bytes: int = 8 << 30,
    max_text_bytes: int = 16 << 20,
) -> dict[Any, Any]:
    """Audit profiles recursively without importing or executing inspected code.

    Every limit produces an explicit issue. Symlinks are observed and hashed but
    marked unsuitable for packaging until importer mutation protections apply.
    All pins in execution profiles and their parent/staging profiles are audited.
    Historical verification/data JSON leaves remain explicit review items rather
    than recursively treating old research receipts as execution dependencies.
    Source scanning reports candidate references,
    not a proof of the complete C preprocessor/Python import/runtime graph.
    """
    if min(max_files, max_total_bytes, max_text_bytes) <= 0:
        raise ValueError("inspection bounds must be positive")
    roots = {
        "source": Path(source_profile).absolute(),
        "runtime": Path(runtime_profile).absolute(),
        "encoder": Path(encoder_config).absolute(),
    }
    queue: deque[str] = deque()
    files: dict[str, dict[Any, Any]] = {}
    edges: list[dict[Any, Any]] = []
    issues: list[dict[Any, Any]] = []
    bindings: list[dict[Any, Any]] = []
    source_roots: set[Path] = set()
    total = 0
    seen_issues = set()
    record_limit = 100000
    omitted_records: Counter[Any] = Counter()

    def issue(code: str, path: str, detail: str, **extra: Any) -> None:
        key = (code, path, detail, json.dumps(extra, sort_keys=True))
        if key not in seen_issues:
            if len(issues) >= record_limit:
                omitted_records["issues"] += 1
                return
            seen_issues.add(key)
            issues.append({"code": code, "path": path, "detail": detail, **extra})

    def add(
        path: Path,
        context: str,
        *,
        expected: dict[Any, Any] | None = None,
        logical: str | None = None,
        parent: str | None = None,
        relation: str = "json_pin",
        line: int | None = None,
    ) -> None:
        path = Path(os.path.abspath(path))  # preserve symlink spelling for the audit
        key = str(path)
        if parent is not None and not files.get(parent, {}).get("expand_dependencies", True):
            context = "verification:" + context
        expand = not (
            context.startswith("verification:")
            or "evidence" in context
            or "source_contracts" in context
            or (path.suffix == ".json" and context.startswith("sources["))
            or (
                relation == "source_literal"
                and classify_dependency(path, context) == "verification"
            )
        )
        if (
            path.suffix == ".json"
            and parent is not None
            and not re.search(r"(?:parent_profile|staging_profile|source_profile|config)$", context)
        ):
            expand = False
        if parent is not None:
            if len(edges) < record_limit:
                edges.append(
                    {
                        "from": parent,
                        "to": key,
                        "relation": relation,
                        "context": context,
                        **({"line": line} if line else {}),
                    }
                )
            else:
                omitted_records["edges"] += 1
        if key not in files:
            if len(files) >= max_files:
                issue(
                    "FILE_LIMIT",
                    key,
                    "dependency not inspected because max_files was reached",
                    context=context,
                )
                return
            files[key] = {
                "path": key,
                "logical_name": logical or path.name,
                "roles": [],
                "expected_pins": [],
                "status": "pending",
                "expand_dependencies": expand,
            }
            queue.append(key)
        row = files[key]
        row["expand_dependencies"] = row["expand_dependencies"] or expand
        role = classify_dependency(path, context)
        if role not in row["roles"]:
            row["roles"].append(role)
        if expected is not None and expected not in row["expected_pins"]:
            row["expected_pins"].append(expected)

    for role, path in roots.items():
        add(path, f"{role}_profile", logical=f"profiles/{role}.json", relation="root")

    def json_walk(value: Any, parent: str, context: str = "", depth: int = 0) -> None:
        if depth > 128:
            issue(
                "JSON_DEPTH_LIMIT",
                parent,
                "nested JSON traversal exceeds 128 levels",
                context=context,
            )
            return
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and {"bytes", "sha256"} <= value.keys():
                expected = {k: value[k] for k in ("bytes", "sha256")}
                if (
                    type(expected["bytes"]) is not int
                    or expected["bytes"] < 0
                    or not isinstance(expected["sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", expected["sha256"]) is None
                ):
                    issue("INVALID_PIN", parent, "malformed pin", context=context, pin=value)
                pin_path = Path(value["path"])
                if not pin_path.is_absolute():
                    pin_path = Path(parent).parent / pin_path
                add(pin_path, context, expected=expected, parent=parent)
            if isinstance(value.get("relative"), str) and isinstance(value.get("pin"), dict):
                declared = value["pin"]
                if isinstance(declared.get("path"), str):
                    pin_path = Path(declared["path"])
                    if not pin_path.is_absolute():
                        pin_path = Path(parent).parent / pin_path
                    add(
                        pin_path,
                        context,
                        logical="sources/" + value["relative"],
                        parent=parent,
                        expected={k: declared.get(k) for k in ("bytes", "sha256")},
                    )
            for name, item in value.items():
                if name == "source_root" and isinstance(item, str):
                    source_roots.add(Path(item))
                if (
                    name == "relative"
                    and isinstance(item, str)
                    and isinstance(value.get("pin"), dict)
                ):
                    pin_path = os.path.abspath(value["pin"].get("path", ""))
                    if pin_path in files:
                        files[pin_path]["logical_name"] = "sources/" + item
                if name != "path":
                    json_walk(item, parent, f"{context}.{name}".strip("."), depth + 1)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                json_walk(item, parent, f"{context}[{index}]", depth + 1)
        elif isinstance(value, str) and value.startswith("/") and _PATH_KEY.search(context):
            path = Path(value)
            issue(
                "UNPINNED_JSON_PATH",
                parent,
                "path reference has no content pin; access role needs review",
                context=context,
                reference=value,
                exists=path.exists(),
            )
            if path.is_file() and files[parent]["expand_dependencies"]:
                add(path, context, parent=parent, relation="unpinned_json_path")

    def resolve_reference(
        parent: Path, reference: str, *, include_roots: bool = False
    ) -> Path | None:
        cleaned = reference.replace("\\\\", "/").replace("\\", "/")
        # The private Wine worker uses its default Z: mapping for Unix inputs.
        if cleaned.lower().startswith("z:/"):
            cleaned = cleaned[2:]
        path = Path(cleaned)
        if path.is_absolute():
            return path
        candidates = [parent.parent / path]
        if include_roots:
            candidates.extend(root / path for root in sorted(source_roots))
        existing = [candidate for candidate in candidates if candidate.is_file()]
        return existing[0] if existing else None

    while queue:
        key = queue.popleft()
        path, row = Path(key), files[key]
        try:
            info = path.stat()
            row["symlink"] = path.is_symlink() or path.resolve() != path
            row["resolved_path"] = str(path.resolve())
            if not stat.S_ISREG(info.st_mode):
                row["status"] = "not_regular_file"
                issue("NOT_REGULAR_FILE", key, "dependency is not an ordinary file")
                continue
            if total + info.st_size > max_total_bytes:
                row["status"] = "byte_limit"
                issue("BYTE_LIMIT", key, "dependency not read because max_total_bytes was reached")
                continue
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            after = path.stat()
            total += info.st_size
            row.update(bytes=info.st_size, sha256=digest, status="observed_unpinned")
            if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                row["status"] = "changed_during_read"
                issue("MUTATED_DURING_READ", key, "dependency changed while hashing")
            if row["symlink"]:
                issue(
                    "SYMLINK_DEPENDENCY",
                    key,
                    "symlink target observed; importer must freeze and verify target",
                    target=row["resolved_path"],
                )
            if path.suffix.lower() not in _TEXT:
                if path.suffix.lower() == ".dll" and "native_image_or_derivation" in row["roles"]:
                    for sibling in sorted(path.parent.glob("*.dll")):
                        if sibling != path:
                            add(
                                sibling,
                                "native_image_adjacent_library_candidate",
                                parent=key,
                                relation="adjacent_library_candidate",
                            )
                if path.suffix.lower() in {".dll", ".exe", ".so"} or "/usr/" in key:
                    issue(
                        "BINARY_DEPENDENCIES_UNRESOLVED",
                        key,
                        "shared libraries, loader, compiler support files or runtime data are not statically closed",
                    )
                continue
            if info.st_size > max_text_bytes:
                issue(
                    "TEXT_LIMIT",
                    key,
                    "source references not scanned because max_text_bytes was reached",
                )
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                row["status"] = "changed_during_read"
                issue("MUTATED_DURING_READ", key, "source changed between hashing and scanning")
                continue
            text = data.decode("utf-8", errors="replace")
            if path.suffix == ".json":
                if not row["expand_dependencies"]:
                    issue(
                        "PROVENANCE_CONTRACT_LEAF",
                        key,
                        "pinned JSON data/verification leaf; internal paths are not inferred as execution dependencies and require access-policy review",
                    )
                    continue
                try:
                    obj = json.loads(text)
                    normalized = _normalize_json(obj)
                    row["normalized_sha256"] = _sha_json(normalized)
                    row["identity_bytes"] = len(
                        json.dumps(normalized, sort_keys=True, separators=(",", ":"))
                    )
                    json_walk(obj, key)
                except (ValueError, RecursionError, TypeError) as exc:
                    issue("INVALID_JSON", key, str(exc))
                continue
            includes = set()
            if not row["expand_dependencies"]:
                issue(
                    "PROVENANCE_SOURCE_NOT_EXPANDED",
                    key,
                    "historical source contract is hashed; its imports and file operations are not runtime dependencies",
                )
                continue
            for match in _INCLUDE.finditer(text):
                reference = match[2]
                include_line = text.count("\n", 0, match.start()) + 1
                includes.add(reference)
                target = resolve_reference(path, reference, include_roots=True)
                if target is not None:
                    add(
                        target,
                        "source_include",
                        parent=key,
                        relation="source_include",
                        line=include_line,
                    )
                else:
                    issue(
                        "SYSTEM_INCLUDE_UNRESOLVED"
                        if match[1] == "<"
                        else "SOURCE_INCLUDE_UNRESOLVED",
                        key,
                        "include not resolved from source parent or declared roots",
                        line=include_line,
                        reference=reference,
                    )
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text)
                    for node in ast.walk(tree):
                        if not isinstance(node, (ast.Import, ast.ImportFrom)):
                            continue
                        if isinstance(node, ast.ImportFrom):
                            names = (
                                [node.module]
                                if node.module
                                else [alias.name for alias in node.names]
                            )
                            if node.module:
                                names += [
                                    node.module + "." + alias.name
                                    for alias in node.names
                                    if alias.name != "*"
                                ]
                            base = path.parent
                            for _ in range(max(0, node.level - 1)):
                                base = base.parent
                            search_roots = [base] if node.level else list(path.parents)
                        else:
                            names = [alias.name for alias in node.names]
                            search_roots = list(path.parents)
                        for name in names:
                            fragment = Path(*name.split("."))
                            candidates: list[Path] = []
                            for ancestor in search_roots:
                                candidates.extend(
                                    (
                                        ancestor / fragment.with_suffix(".py"),
                                        ancestor / fragment / "__init__.py",
                                    )
                                )
                            target = next((p for p in candidates if p.is_file()), None)
                            if target:
                                add(
                                    target,
                                    "python_import",
                                    parent=key,
                                    relation="python_import",
                                    line=node.lineno,
                                )
                            elif (
                                isinstance(node, ast.Import)
                                or not node.module
                                or name == node.module
                            ):
                                issue(
                                    "PYTHON_IMPORT_UNRESOLVED",
                                    key,
                                    "stdlib, external or dynamic package requires runtime inventory",
                                    line=node.lineno,
                                    reference=name,
                                )
                except (SyntaxError, ValueError) as exc:
                    issue("PYTHON_PARSE_ERROR", key, str(exc))
            for lineno, line in enumerate(text.splitlines(), 1):
                values = sorted(set(_HEX.findall(line)))
                if (
                    values
                    and re.search(r"[a-zA-Z_]", _HEX.sub("", line))
                    and (path.suffix in {".h", ".hpp", ".cpp", ".c", ".inc", ".in"})
                ):
                    if len(bindings) >= record_limit:
                        omitted_records["binding_candidates"] += 1
                        continue
                    bindings.append(
                        {
                            "path": key,
                            "line": lineno,
                            "values": values,
                            "kind": "native_address_candidate"
                            if any(int(x, 16) >= 0x10000000 for x in values)
                            else "layout_or_constant_candidate",
                            "excerpt": line.strip()[:300],
                            "semantics_verified": False,
                        }
                    )
                for match in _LITERAL.finditer(line):
                    literal = match[1]
                    if literal in includes or not (
                        "/" in literal
                        or "\\" in literal
                        or re.search(r"\.(?:h|inc|json|dat|dll|exe|bin|py|xs)$", literal)
                    ):
                        continue
                    # Percent substitutions and source concatenation remain explicit uncertainties.
                    if "%" in literal or "{" in literal or "}" in literal:
                        issue(
                            "DYNAMIC_PATH",
                            key,
                            "formatted file/path literal requires runtime tracing",
                            line=lineno,
                            reference=literal,
                        )
                        continue
                    target = resolve_reference(path, literal)
                    if target is not None and target.is_file():
                        add(
                            target,
                            "source_literal",
                            parent=key,
                            relation="source_literal",
                            line=lineno,
                        )
                    else:
                        issue(
                            "SOURCE_LITERAL_UNRESOLVED",
                            key,
                            "candidate file/path literal may be generated, output, optional or missing",
                            line=lineno,
                            reference=literal,
                        )
                if _ACCESS.search(line):
                    issue(
                        "DYNAMIC_ACCESS_REVIEW",
                        key,
                        "file/loader access requires runtime tracing, including literal calls",
                        line=lineno,
                        excerpt=line.strip()[:300],
                    )
        except (OSError, ValueError) as exc:
            row["status"] = "missing" if isinstance(exc, FileNotFoundError) else "unreadable"
            issue(
                "MISSING_FILE" if row["status"] == "missing" else "UNREADABLE_FILE", key, str(exc)
            )

    # Pins may be found after a file was inspected. Evaluate them after traversal.
    for row in files.values():
        if row["status"] not in {"observed_unpinned", "verified"}:
            continue
        pins = row["expected_pins"]
        if pins:
            actual = {"bytes": row["bytes"], "sha256": row["sha256"]}
            row["status"] = "verified" if all(pin == actual for pin in pins) else "changed"
            if row["status"] == "changed":
                issue(
                    "PIN_MISMATCH",
                    row["path"],
                    "observed size or sha256 differs from one or more pins",
                    actual=actual,
                    expected=pins,
                )
    rows = sorted(files.values(), key=lambda row: row["path"])
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "profiles": {k: str(v) for k, v in roots.items()},
        "files": rows,
        "edges": edges,
        "issues": issues,
        "binding_candidates": bindings,
        "inventory_content_id": content_identity(rows),
        "native_execution": False,
        "native_compatibility_verified": False,
        "dependency_closure_proven": False,
        "closure_policy": "static candidates only; runtime file tracing, binary dependencies, generated inputs and mutation-safe packaging remain required",
        "limits": {
            "max_files": max_files,
            "max_total_bytes": max_total_bytes,
            "max_text_bytes": max_text_bytes,
            "max_records_per_collection": record_limit,
        },
        "omitted_records": dict(omitted_records),
        "summary": {
            "files": len(rows),
            "bytes_hashed": total,
            "statuses": dict(sorted(Counter(row["status"] for row in rows).items())),
            "issues": dict(sorted(Counter(row["code"] for row in issues).items())),
            "binding_candidates": len(bindings),
        },
    }
    if replay is not None:
        manifest["replay"] = inspect_replay_identity(replay)
    return manifest


def inspect_replay_identity(path: Path) -> dict[Any, Any]:
    """Read identity without selecting an engine or treating filename as proof."""
    from vantage.native_input import describe_native_input
    from vantage.replay import read_replay

    path = Path(path).absolute()
    result: dict[str, Any] = {
        "path": str(path),
        "engine_selected": None,
        "steam_build_id": None,
        "steam_build_id_source": "not present in replay header",
        "native_compatibility_verified": False,
    }
    try:
        with path.open("rb") as stream:
            result["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        info = read_replay(path)
        result.update(
            replay_build=info.build,
            replay_build_is_masked_hint=True,
            filename_game_version_hint=info.game_version,
            save_version=info.save_version,
            chapters=info.chapters,
            version=info.version,
        )
        if info.build != 54800:
            result.update(
                status="unsupported_identity",
                reason="no qualified engine selected for this replay identity",
            )
            return result
        try:
            description = describe_native_input(path)
            result["native_input"] = {
                name: getattr(description, name)
                for name in (
                    "build",
                    "save_version",
                    "options_version",
                    "dataset_id",
                    "game_mode",
                    "selected_content_mode",
                    "checksum_sync_count",
                    "initial_clock_ms",
                    "final_clock_ms",
                )
            }
            result.update(
                status="described_unqualified",
                reason="descriptor alone does not establish package compatibility",
            )
        except (ValueError, OSError) as exc:
            result.update(status="unsupported_input", reason=str(exc))
    except (ValueError, OSError) as exc:
        result.update(status="unreadable_identity", reason=str(exc))
    return result
