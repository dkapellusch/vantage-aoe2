"""Installed Schema versus its pinned archived original; no overlay or target runs."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

from vantage import schema as installed_schema

BEFORE = Path(__file__).parent / "fixtures/schema-before-name-index.py"
EXPECTED_BEFORE = "323a018f58d8ddc75addc2b088492d7a8f85f07245c5387790ced991f41547d6"


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def schemas():
    assert hashlib.sha256(BEFORE.read_bytes()).hexdigest() == EXPECTED_BEFORE
    original = load_source("schema_before_name_index", BEFORE)
    return original, installed_schema


def data(names):
    return {"models": {mid: {"name": name, "fields": {}} for mid, name in names}}


def result(schema, query):
    try:
        return ("ok", schema.model_id(query))
    except Exception as error:
        return (type(error), error.args)


def test_all_installed_model_names_and_fields_are_differentially_equal(schemas):
    old, new = schemas
    for mid, name in old.SCHEMA._names.items():
        assert old.SCHEMA.model_id(name) == new.SCHEMA.model_id(name)
        assert old.SCHEMA.name(mid) == new.SCHEMA.name(mid)
        assert {fid: dataclasses.asdict(spec) for fid, spec in old.SCHEMA.fields(mid).items()} == {
            fid: dataclasses.asdict(spec) for fid, spec in new.SCHEMA.fields(mid).items()
        }
        for fid in old.SCHEMA.fields(mid):
            assert old.SCHEMA.narrow(mid, fid) == new.SCHEMA.narrow(mid, fid)


@pytest.mark.parametrize(
    "names,query,expected",
    [
        ([("9", "same"), ("2", "same")], "same", 9),
        ([("01", "old"), ("2", "same"), ("1", "same")], "same", 1),
        ([("01", "old"), ("2", "same"), ("1", "new")], "new", 1),
        ([("3", ""), ("4", "World"), ("5", "world")], "", 3),
        ([("3", ""), ("4", "World"), ("5", "world")], "world", 5),
        ([("8", "é"), ("7", "e\u0301")], "é", 8),
    ],
)
def test_duplicate_name_numeric_alias_order_case_and_unicode(schemas, names, query, expected):
    old, new = schemas
    payload = data(names)
    assert old.Schema(payload).model_id(query) == new.Schema(payload).model_id(query) == expected


@pytest.mark.parametrize(
    "names,query",
    [
        ([], "missing"),
        ([("0", "root")], "missing"),
        ([("01", "old"), ("2", "same"), ("1", "new")], "old"),
        ([("0", "root")], []),
        ([("0", "root")], 123),
        ([("0", "root")], None),
    ],
)
def test_exact_keyerror_type_and_args_for_missing_queries(schemas, names, query):
    old, new = schemas
    assert result(old.Schema(data(names)), query) == result(new.Schema(data(names)), query)
    for cls in (old.Schema, new.Schema):
        with pytest.raises(KeyError) as caught:
            cls(data(names)).model_id(query)
        assert len(caught.value.args) == 1 and caught.value.args[0] is query


@pytest.mark.parametrize(
    "names,query,expected",
    [
        ([("0", ["unhashable"])], ["unhashable"], 0),
        ([("9", 1), ("2", True)], True, 9),
        ([("0", None)], None, 0),
    ],
)
def test_custom_nonstring_names_keep_constructor_and_equality_semantics(
    schemas, names, query, expected
):
    old, new = schemas
    payload = data(names)
    assert old.Schema(payload).model_id(query) == new.Schema(payload).model_id(query) == expected


def test_string_subclasses_and_nonstring_equivalence_use_legacy_comparison(schemas):
    class Equal:
        __hash__ = None

        def __eq__(self, other):
            return other == "root"

    class Weird(str):
        def __eq__(self, other):
            return other == "root"

    old, new = schemas
    for query in (Equal(), Weird("different")):
        assert (
            old.Schema(data([("2", "root")])).model_id(query)
            == new.Schema(data([("2", "root")])).model_id(query)
            == 2
        )
    for cls in (old.Schema, new.Schema):
        assert cls(data([("5", Weird("different"))])).model_id("root") == 5


def test_constructor_snapshots_input_names_as_before(schemas):
    old, new = schemas
    payload = data([("0", "first")])
    left, right = old.Schema(payload), new.Schema(payload)
    payload["models"]["0"]["name"] = "changed"
    assert left.model_id("first") == right.model_id("first") == 0
    assert result(left, "changed") == result(right, "changed")


@pytest.mark.parametrize("backward", [False, True])
def test_actual_patch_decoder_is_equal_with_archived_and_installed_schema(schemas, backward):
    from tests.helpers import PatchBuilder
    from vantage.patch import Patcher

    old, new = schemas
    schema = old.SCHEMA
    mid = schema.model_id

    def fid(model, field):
        return schema.fid(mid(model), field)

    patch = PatchBuilder().create(fid("Root", "world"), mid("World"))
    patch.assign(fid("World", "time"), "UInt32", 1234)
    patch.assign(fid("World", "gameEnded"), "Boolean", False)
    patch.create_key(fid("World", "players"), mid("Player"), 1)
    patch.assign(fid("Player", "name"), "String", "Ünïcode")
    patch.create(fid("Player", "attributes"), mid("PlayerAttributes"))
    patch.assign(fid("PlayerAttributes", "food"), "Float", 200.0)
    patch.pop().pop().pop()
    raw = patch.backward() if backward else patch.forward()
    left, right = Patcher(old.SCHEMA), Patcher(new.SCHEMA)
    left.apply(raw)
    right.apply(raw)
    assert left.root == right.root
    assert left.ops == right.ops
