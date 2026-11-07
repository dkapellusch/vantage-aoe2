"""Bounded synthetic cache tests; no actual recording, game, browser or benchmark."""

from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.helpers import Frame, delta, game_frames, set_entity, set_world, spawn
from tests.test_gamedata import _fake_install
from tests.test_timeline import _missile_timeline
from vantage import playback_index as cache
from vantage.frames import RecordingWriter, read_frames
from vantage.gamedata import GameData, ModConfig
from vantage.native_conversion import ConversionCancelled, pin
from vantage.native_session import SessionPort, Ticket
from vantage.playback_data import content_manifest, fresh_data
from vantage.playback_index import (
    SCHEMA,
    CacheMiss,
    Cancelled,
    ReadOnlyTimeline,
    Store,
    canonical,
    file_pin,
    identity,
    load_completed,
    publish,
    restore,
)
from vantage.server import _tree_costs
from vantage.timeline import Timeline


class CacheTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.recording = self.root / "synthetic.vrec"
        with RecordingWriter(self.recording) as writer:
            for frame in game_frames(12):
                writer.write(frame)
        self.cache = self.root / "cache"
        self.raw_data = GameData(None, mods=ModConfig(live_mods=[]))

    def tearDown(self):
        self.temp.cleanup()

    def ordinary(self, stop=None, data=None):
        timeline = Timeline(data or fresh_data(self.raw_data))
        expected = identity(self.recording, timeline.data)
        for frame in read_frames(self.recording):
            if stop is not None and stop.is_set():
                raise Cancelled("ordinary load cancelled")
            timeline.feed(frame)
        timeline.finish()
        self.assertEqual(expected, identity(self.recording, timeline.data))
        timeline._index_source_identity = expected
        return timeline

    def saved(self, data=None):
        timeline = self.ordinary(data=data)
        expected = identity(self.recording, timeline.data)
        directory = publish(timeline, self.recording, self.cache, expected)
        return timeline, directory

    def compare_queries(self, a, b):
        self.assertEqual(a.status(), b.status())
        self.assertEqual(a.match, b.match)
        self.assertEqual(a.map, b.map)
        self.assertEqual(a.sprites, b.sprites)
        self.assertEqual(a.series_json(), b.series_json())
        for lang in ("en", "de", "xx"):
            self.assertEqual(a.catalog.to_json(lang), b.catalog.to_json(lang))
            self.assertEqual(a.data.color_grade_names(lang), b.data.color_grade_names(lang))
            for civ in range(len(a.data.civs)):
                tree_a, tree_b = a.data.tech_tree(civ, lang), b.data.tech_tree(civ, lang)
                if tree_a is not None:
                    _tree_costs(tree_a, a)
                    _tree_costs(tree_b, b)
                self.assertEqual(tree_a, tree_b)
        for when in (None, -1, 0, 500, 1000, 4500, 11000, 12000, 999999):
            self.assertEqual(a.view_at(when), b.view_at(when))
            self.assertEqual(a.summary(when), b.summary(when))
            if when is not None:
                self.assertEqual(a.trees_at(when), b.trees_at(when))
                self.assertEqual(a.terrain_at(when), b.terrain_at(when))
            for eid in (101, 102, 103, 104, -5, 999999):
                self.assertEqual(a.unit_stats(eid, when), b.unit_stats(eid, when))
            self.assertEqual(
                a.group_stats([101, 102, 104], when), b.group_stats([101, 102, 104], when)
            )
            for owner, mid in a.master_log:
                self.assertEqual(a.master_stats(owner, mid, when), b.master_stats(owner, mid, when))
        for start, end in ((-1, 0), (3500, 4500), (0, 999999), (100, 99)):
            self.assertEqual(a.events_between(start, end), b.events_between(start, end))
        tree = {"nodes": [{"kind": "unit", "id": 83}], "layout": {"rows": []}}
        before, after = copy.deepcopy(tree), copy.deepcopy(tree)
        _tree_costs(before, a)
        _tree_costs(after, b)
        self.assertEqual(before, after)

    def test_all_queries_roundtrip_without_frame_decode_or_patcher(self):
        ordinary, _ = self.saved()
        with (
            patch("vantage.frames.read_frames", side_effect=AssertionError("no replay")),
            patch("vantage.patch.Patcher.apply", side_effect=AssertionError("no patch")),
        ):
            cached = restore(self.recording, fresh_data(self.raw_data), self.cache)
        try:
            self.assertIsNone(cached.patcher)
            reads = cached._index_store.blobs_read
            cached.view_at(4300)
            self.assertGreater(cached._index_store.blobs_read, reads)
            self.compare_queries(ordinary, cached)
            self.assertEqual(cached.wait_change(cached.version, 5), cached.version)
            self.assertFalse(cached.game_ended)  # recording complete is not game end
            for name in ("feed", "finish", "add_event", "oracle_chat"):
                with self.assertRaises(TypeError):
                    getattr(cached, name)(None)
        finally:
            cached.close()

    def test_projectile_and_unflushed_unit_track_tail_roundtrip(self):
        captured = []
        original_feed = Timeline.feed

        def collect(timeline, frame):
            captured.append(frame)
            return original_feed(timeline, frame)

        with patch.object(Timeline, "feed", collect):
            timeline = _missile_timeline()
        timeline.data = fresh_data(self.raw_data)
        # Unit movement in the last unfinished track must survive too.
        movement = Frame(
            time=1400,
            patch=delta(
                1400,
                set_entity(104, "Entity", "worldX", "Float", 9.0),
                spawn(-6, 3, 1, 1.0, 1.0, model="MissileEntity", action=False),
            ).forward(),
        )
        timeline.feed(movement)
        captured.append(movement)
        self.assertTrue(timeline._track_buf)
        timeline.finish()
        self.assertTrue(timeline.missiles)
        self.assertTrue(timeline.unit_tracks)
        self.assertTrue(timeline._missile_buf)
        self.recording.unlink()
        with RecordingWriter(self.recording) as writer:
            for frame in captured:
                writer.write(frame)
        timeline._index_source_identity = identity(self.recording, timeline.data)
        publish(timeline, self.recording, self.cache, timeline._index_source_identity)
        cached = restore(self.recording, fresh_data(self.raw_data), self.cache)
        try:
            self.compare_queries(timeline, cached)
            self.assertEqual(timeline._track_buf, cached._track_buf)
            self.assertEqual(timeline._missile_buf, cached._missile_buf)
        finally:
            cached.close()

    def test_corrupt_database_falls_back_to_ordinary_ingestion(self):
        _, directory = self.saved()
        (directory / "index.sqlite3").write_bytes(b"corrupt cache; source VREC retained")
        with patch.object(cache, "ingest_recording", wraps=cache.ingest_recording) as ingest:
            data, result = load_completed(self.recording, self.raw_data, self.cache)
            self.assertEqual(ingest.call_count, 1)
            self.assertNotIsInstance(result, ReadOnlyTimeline)
            self.assertIs(result.data, data)
        cached = restore(self.recording, self.raw_data, self.cache)
        cached.close()

    def test_pending_and_uncommitted_work_never_count_as_hit(self):
        pending = self.cache / ".pending-abandoned"
        pending.mkdir(parents=True)
        (pending / "index.sqlite3").write_bytes(b"partial")
        with self.assertRaises(CacheMiss):
            restore(self.recording, fresh_data(self.raw_data), self.cache)

    def test_changed_recording_and_consumer_identity_cannot_hit(self):
        _, directory = self.saved()
        with self.recording.open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaises(CacheMiss):
            restore(self.recording, fresh_data(self.raw_data), self.cache)
        self.assertTrue((directory / "committed.json").is_file())
        with (
            patch.object(cache, "source_identity", return_value={"different_consumer": True}),
            self.assertRaises(CacheMiss),
        ):
            restore(self.recording, fresh_data(self.raw_data), self.cache)

    def test_changed_input_during_ingestion_does_not_publish(self):
        timeline = self.ordinary()
        expected = identity(self.recording, timeline.data)
        self.recording.write_bytes(b"new generation bytes")
        with self.assertRaises(CacheMiss):
            publish(timeline, self.recording, self.cache, expected)
        self.assertFalse(list(self.cache.glob("*/committed.json")))

    def test_read_only_sqlite_and_unknown_state_tag_rejected(self):
        _, directory = self.saved()
        cached = restore(self.recording, fresh_data(self.raw_data), self.cache)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                cached._index_store.db.execute("DELETE FROM blobs")
        finally:
            cached.close()
        db = directory / "index.sqlite3"
        with sqlite3.connect(db) as connection:
            payload = {
                "schema": SCHEMA,
                "state": ["arbitrary_python_class", "os.system"],
                "keyframes": [],
            }
            connection.execute("UPDATE state SET data=?", (canonical(payload),))
        commit = directory / "committed.json"
        manifest = json.loads(commit.read_text())
        manifest["database"] = file_pin(db)
        commit.write_bytes(canonical(manifest))
        with self.assertRaises(CacheMiss):
            restore(self.recording, fresh_data(self.raw_data), self.cache)

    def test_only_completed_error_free_timelines_publish(self):
        timeline = self.ordinary()
        for key, value in (("complete", False), ("errors", 1), ("desynced", True)):
            before = getattr(timeline, key)
            setattr(timeline, key, value)
            with self.assertRaises(CacheMiss):
                publish(
                    timeline, self.recording, self.cache, identity(self.recording, timeline.data)
                )
            setattr(timeline, key, before)

    def test_completed_cache_hit_does_not_call_ingest(self):
        self.saved()
        with patch.object(cache, "ingest_recording", side_effect=AssertionError("replay on hit")):
            data, result = load_completed(self.recording, self.raw_data, self.cache)
        self.assertIsInstance(result, ReadOnlyTimeline)
        self.assertIs(data, result.data)
        result.close()

    def test_shared_lazy_data_is_rejected_and_new_job_is_fresh(self):
        with self.assertRaises(CacheMiss):
            identity(self.recording, self.raw_data)
        game = _fake_install(self.root)
        old = GameData(game, mods=ModConfig(live_mods=[]))
        self.assertEqual(old.string(5121), "Villager")
        strings = game / "resources/en/strings/key-value/key-value-strings-utf8.txt"
        strings.write_text('5121 "Changed after earlier Session cached table"\n')
        self.assertEqual(old.string(5121), "Villager")
        self.assertEqual(fresh_data(old).string(5121), "Changed after earlier Session cached table")

    def test_completed_helper_uses_bound_ordinary_ingestor_then_cache_hit(self):
        _, ordinary = load_completed(self.recording, self.raw_data, self.cache)
        self.assertIsNotNone(ordinary._index_source_identity)
        _, cached = load_completed(self.recording, self.raw_data, self.cache)
        self.assertIsInstance(cached, ReadOnlyTimeline)
        self.compare_queries(ordinary, cached)
        cached.close()

    def test_cancellation_during_serialization_removes_pending_entry(self):
        from vantage import playback_index as cache

        timeline = self.ordinary()
        stop = threading.Event()
        original = cache.Writer.blob

        def cancel_on_blob(writer, value):
            result = original(writer, value)
            stop.set()
            return result

        with patch.object(cache.Writer, "blob", cancel_on_blob), self.assertRaises(Cancelled):
            publish(timeline, self.recording, self.cache, timeline._index_source_identity, stop)
        self.assertFalse(list(self.cache.glob("*/committed.json")))
        self.assertFalse(list(self.cache.glob(".pending-*")))

    def test_unbound_timeline_cannot_be_misattributed_to_recording(self):
        timeline = self.ordinary()
        del timeline._index_source_identity
        with self.assertRaises(CacheMiss):
            publish(timeline, self.recording, self.cache, identity(self.recording, timeline.data))

    def test_actual_game_end_and_skipped_source_timesteps_are_preserved(self):
        frames = game_frames(12)
        frames.append(
            Frame(
                time=14000,
                skipped=1,
                patch=delta(14000, set_world("gameEnded", "Boolean", True)).forward(),
            )
        )
        self.recording.unlink()
        with RecordingWriter(self.recording) as writer:
            for frame in frames:
                writer.write(frame)
        ordinary, _ = self.saved()
        self.assertTrue(ordinary.game_ended)
        self.assertTrue(ordinary.skips)
        cached = restore(self.recording, fresh_data(self.raw_data), self.cache)
        try:
            self.compare_queries(ordinary, cached)
            self.assertTrue(cached.game_ended)
        finally:
            cached.close()

    def test_active_old_reader_survives_atomic_cache_replacement(self):
        timeline, _ = self.saved()
        old = restore(self.recording, fresh_data(self.raw_data), self.cache)
        try:
            publish(timeline, self.recording, self.cache, timeline._index_source_identity)
            self.assertEqual(old.view_at(1000), timeline.view_at(1000))
        finally:
            old.close()

    def test_recording_replacement_during_restore_rejected_and_database_closed(self):
        self.saved()
        changed, stores = [], []
        original = Store.decode

        def replace_during_decode(store, value, depth=0):
            result = original(store, value, depth)
            if depth == 0 and not changed:
                changed.append(True)
                stores.append(store)
                self.recording.unlink()
                with RecordingWriter(self.recording) as writer:
                    for frame in game_frames(13):
                        writer.write(frame)
            return result

        with patch.object(Store, "decode", replace_during_decode), self.assertRaises(CacheMiss):
            restore(self.recording, self.raw_data, self.cache)
        self.assertTrue(changed)
        with self.assertRaises(sqlite3.ProgrammingError):
            stores[0].db.execute("SELECT 1")

    def test_installed_metadata_change_during_restore_rejected(self):
        game = _fake_install(self.root)
        raw = GameData(game, mods=ModConfig(live_mods=[]))
        self.saved(fresh_data(raw))
        original = Store.decode
        changed = []

        def change_strings(store, value, depth=0):
            result = original(store, value, depth)
            if depth == 0 and not changed:
                changed.append(True)
                strings = game / "resources/en/strings/key-value/key-value-strings-utf8.txt"
                strings.write_text('5121 "New metadata during cache hydration"\n')
            return result

        with patch.object(Store, "decode", change_strings), self.assertRaises(CacheMiss):
            restore(self.recording, raw, self.cache)
        self.assertTrue(changed)

    def test_prewarmed_data_is_freshened_before_selecting_current_content_cache(self):
        game = _fake_install(self.root)
        dat = game / "resources/_common/dat"
        (dat / "eras.json").write_text(json.dumps([{"Name": "base", "Ages": [{"NameId": 5121}]}]))
        raw = GameData(game, mods=ModConfig(live_mods=[]))
        warmed = fresh_data(raw)
        self.assertEqual(warmed.string(5121), "Villager")
        strings = game / "resources/en/strings/key-value/key-value-strings-utf8.txt"
        strings.write_text('5121 "Current era name"\n')
        ordinary, _ = self.saved(fresh_data(raw))
        cached = restore(self.recording, warmed, self.cache)
        try:
            self.assertIsNot(cached.data, warmed)
            self.assertIs(cached.catalog.data, cached.data)
            self.assertEqual(warmed.string(5121), "Villager")
            self.assertEqual(cached.data.string(5121), "Current era name")
            self.assertEqual(cached.catalog.to_json("en"), ordinary.catalog.to_json("en"))
            self.assertEqual(
                cached.catalog.to_json("en")["eras"]["base"]["ages"][0]["name"], "Current era name"
            )
        finally:
            cached.close()

    def test_bad_cached_node_shape_or_unknown_model_is_rejected(self):
        store = Store(None, None)
        for value in (
            ["n", 9, 123, True],
            ["n", 999999, ["d", []], True],
            ["n", 9, ["d", [["wrong key", 0]]], True],
        ):
            with self.assertRaises(CacheMiss):
                store.decode(value)

    def test_snapshot_heap_settling_retained_on_miss_and_not_run_on_hit(self):
        with patch("vantage.timeline.settle_heap") as settle:
            _, ordinary = load_completed(self.recording, self.raw_data, self.cache)
            self.assertGreater(settle.call_count, 0)
            self.assertEqual(
                settle.call_count, sum(f.is_snapshot for f in read_frames(self.recording))
            )
        with patch("vantage.timeline.settle_heap", side_effect=AssertionError("hit settled")):
            _, cached = load_completed(self.recording, self.raw_data, self.cache)
        try:
            self.compare_queries(ordinary, cached)
        finally:
            cached.close()

    def test_index_write_error_preserves_ordinary_ingestion(self):
        with patch.object(cache, "publish", side_effect=OSError("cache volume unavailable")):
            data, ordinary = load_completed(self.recording, self.raw_data, self.cache)
        self.assertTrue(ordinary.complete)
        self.assertEqual(ordinary.frames, len(game_frames(12)))
        self.assertIs(data, ordinary.data)
        self.assertNotIsInstance(ordinary, ReadOnlyTimeline)

    def test_installed_mode_mod_manifest_and_all_queries_roundtrip(self):
        game = _fake_install(self.root)
        dat = game / "resources/_common/dat"
        (dat / "unitlines.json").write_text(
            json.dumps(
                {
                    "UnitLines": [
                        {"LineID": 1, "Name": "Knight", "IDChain": [38], "Identifier": "knight"}
                    ]
                }
            )
        )
        trees = dat / "CivTechTrees"
        trees.mkdir()
        civs = {
            "civilization_list": [
                {"internal_name": "Gaia"},
                {"internal_name": "Britons", "name_string_id": 10271, "tech_tree_name": "BRITONS"},
            ]
        }
        (dat / "civilizations.json").write_text(json.dumps(civs))
        (trees / "BRITONS.json").write_text(
            json.dumps(
                {
                    "civ_techs_buildings": [],
                    "civ_techs_units": [
                        {
                            "Node ID": 38,
                            "Use Type": "Unit",
                            "Name": "Knight",
                            "Age ID": 3,
                            "Node Status": "Available",
                        }
                    ],
                }
            )
        )
        raw = GameData(game, mods=ModConfig(live_mods=[]))
        ordinary, _ = self.saved(fresh_data(raw))
        cached = restore(self.recording, fresh_data(raw), self.cache)
        try:
            self.compare_queries(ordinary, cached)
        finally:
            cached.close()


class NativePortCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "committed/recording.vrec"
        frames = game_frames(12)
        self.header = dict(expected_frames=len(frames), end_ms=12000)
        with RecordingWriter(self.path, self.header) as writer:
            for frame in frames:
                writer.write(frame)
        self.report = dict(
            status="conversion_verified",
            recording=pin(self.path),
            capture_frames=len(frames),
            capture_end_ms=12000,
            game_ended=False,
        )
        self.report_path = self.path.parent / "conversion.json"
        self.marker_path = self.path.parent / "success.json"
        self.write_commit()
        self.cancelled = threading.Event()
        self.ticket = Ticket(
            1,
            threading.Event(),
            GameData(None, mods=ModConfig(live_mods=[])),
            {"replay": "synthetic.aoe2record"},
            self.root / "index",
        )

    def tearDown(self):
        self.temp.cleanup()

    def write_commit(self):
        self.report_path.write_text(json.dumps(self.report))
        self.marker_path.write_text(
            json.dumps(
                dict(status="ready", recording=pin(self.path), conversion=pin(self.report_path))
            )
        )

    def test_native_port_hit_retains_all_validation_and_fresh_returned_data(self):
        data, ordinary, header = SessionPort.load(self.ticket, self.path, self.cancelled)
        self.assertIs(data, ordinary.data)
        self.assertEqual(header["end_ms"], 12000)
        with (
            patch("vantage.frames.read_frames", side_effect=AssertionError("hit replay")),
            patch("vantage.patch.Patcher.apply", side_effect=AssertionError("hit patch")),
        ):
            data, cached, same_header = SessionPort.load(self.ticket, self.path, self.cancelled)
        try:
            self.assertIsInstance(cached, ReadOnlyTimeline)
            self.assertIs(cached.data, data)
            self.assertEqual(header, same_header)
            self.assertEqual(cached.status(), ordinary.status())
            self.assertEqual(cached.view_at(12000), ordinary.view_at(12000))
            self.assertFalse(cached.game_ended)
        finally:
            cached.close()

    def test_native_report_game_end_check_still_rejects_cached_index(self):
        SessionPort.load(self.ticket, self.path, self.cancelled)
        self.report["game_ended"] = True
        self.write_commit()
        with self.assertRaisesRegex(ValueError, "game-ended"):
            SessionPort.load(self.ticket, self.path, self.cancelled)

    def test_native_extent_and_commit_gates_run_before_index_loader(self):
        import vantage.native_session as session_module

        self.report["capture_frames"] += 1
        self.write_commit()
        with (
            patch.object(
                session_module, "load_completed", side_effect=AssertionError("early load")
            ),
            self.assertRaisesRegex(ValueError, "extent"),
        ):
            SessionPort.load(self.ticket, self.path, self.cancelled)

    def test_native_postload_byte_pins_rechecked(self):
        import vantage.native_session as session_module

        original = session_module.load_completed

        def changed_report(*args):
            result = original(*args)
            self.report_path.write_text("changed after successful Timeline load")
            return result

        with (
            patch.object(session_module, "load_completed", changed_report),
            self.assertRaisesRegex(ValueError, "changed while loading"),
        ):
            SessionPort.load(self.ticket, self.path, self.cancelled)

    def test_native_job_or_session_cancellation_propagates(self):
        for event in (self.cancelled, self.ticket.stop):
            event.set()
            with self.assertRaises(ConversionCancelled):
                SessionPort.load(self.ticket, self.path, self.cancelled)
            event.clear()

    def test_private_index_root_comes_only_from_configured_session(self):
        reserved = Ticket(1, threading.Event(), self.ticket.data, self.ticket.source)
        session = SimpleNamespace(
            lock=threading.RLock(),
            native_config=SimpleNamespace(cache_dir=self.root / "configured"),
        )
        session._reserve = lambda *args: (reserved, None)
        selected = SessionPort(session).begin(self.root / "selected.aoe2record")
        self.assertIsNone(reserved.playback_index_root)
        self.assertEqual(selected.playback_index_root, self.root / "configured/playback-index-v2")
        self.assertIs(selected.source, reserved.source)
        self.assertNotIn("playback_index_root", selected.source)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.game = _fake_install(self.root)
        self.mod = self.root / "mod"
        self.maps = self.mod / "resources/_common/random-map-scripts"
        self.maps.mkdir(parents=True)
        self.data = GameData(self.game, mods=ModConfig(live_mods=[self.mod]))

    def tearDown(self):
        self.temp.cleanup()

    def manifest(self):
        return content_manifest(fresh_data(self.data))

    def test_new_higher_priority_metadata_and_mode_directory_invalidate(self):
        old = self.manifest()
        mode = self.game / "modes/Pompeii/resources/_common/dat"
        mode.mkdir(parents=True)
        (mode / "civilizations.json").write_text('{"civilization_list":[]}')
        self.data = self.data.with_mode("Pompeii")
        self.assertNotEqual(old, self.manifest())

    def test_new_language_palette_and_script_candidates_invalidate(self):
        paths = [
            self.game / "resources/de/strings/key-value/new.txt",
            self.game / "resources/_common/palettes/playercolor_red.pal",
            self.maps / "Arabia.RMS",
            self.game / "resources/_common/drs/gamedata_x2/Arabia.rms",
        ]
        for path in paths:
            before = self.manifest()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("new relevant candidate")
            self.assertNotEqual(before, self.manifest())

    def test_mod_scripts_count_even_when_all_rendering_mod_switches_off(self):
        self.assertFalse(any(self.data.mods.enabled.values()))
        before = self.manifest()
        (self.maps / "new.rms").write_text("color_correction 4")
        after = self.manifest()
        self.assertNotEqual(before, after)
        self.assertIn(str(self.mod), after["effective_mod_order"])

    def test_material_png_existence_counts_but_texture_bytes_are_independent(self):
        widget = self.game / "widgetui"
        materials = {
            "GlobalTextures": [{"TextureDef": {"Name": "age", "FileName": "age.png"}}],
            "Materials": [{"MaterialDef": {"Name": "age", "TextureRef": "age"}}],
        }
        (widget / "materials.json").write_text(json.dumps(materials))
        before = self.manifest()
        (widget / "age.png").write_bytes(b"first texture")
        after = self.manifest()
        self.assertNotEqual(before, after)
        (widget / "age.png").write_bytes(b"unrelated pixel change")
        self.assertEqual(after, self.manifest())
        texture = self.game / "resources/_common/terrain/textures/2x/grass.dds"
        texture.parent.mkdir(parents=True)
        texture.write_bytes(b"independent renderer asset")
        self.assertEqual(after, self.manifest())

    def test_next_generation_reresolves_profile_status_after_installing_frozen_data(self):
        profile = self.root / "profile"
        mods = profile / "mods"
        mods.mkdir(parents=True)
        first, second = mods / "first", mods / "second"
        first.mkdir()
        second.mkdir()
        status = mods / "mod-status.json"
        status.write_text(json.dumps({"Mods": [{"Enabled": True, "Priority": 1, "Path": "first"}]}))
        original = GameData(self.game, mods=ModConfig(profiles=[profile]))
        generation1 = fresh_data(original)
        self.assertEqual(generation1.mods.mod_folders(), [first])
        status.write_text(
            json.dumps({"Mods": [{"Enabled": True, "Priority": 1, "Path": "second"}]})
        )
        self.assertEqual(generation1.mods.mod_folders(), [first])
        generation2 = fresh_data(generation1)
        self.assertEqual(generation2.mods.mod_folders(), [second])
        self.assertNotEqual(content_manifest(generation1), content_manifest(generation2))

    def test_mod_priority_order_and_same_size_content_change_invalidate(self):
        other = self.root / "another-mod"
        other.mkdir()
        before = self.manifest()
        self.data.mods.live_mods = [other, self.mod]
        self.assertNotEqual(before, self.manifest())
        path = self.maps / "same.rms"
        path.write_text("color_correction 1")
        before = self.manifest()
        path.write_text("color_correction 2")
        self.assertNotEqual(before, self.manifest())


if __name__ == "__main__":
    unittest.main()
