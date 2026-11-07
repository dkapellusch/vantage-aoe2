"""Check profile selection and its hash boundary at the public entry point."""

import hashlib
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ENTRY = Path(__file__).resolve().parents[1] / "vantage-native.py"
SPEC = importlib.util.spec_from_file_location("vantage_native_entry", ENTRY)
entry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(entry)


class ExecIntercept(Exception):
    pass


class EntryProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.replay = self.root / "match.aoe2record"
        self.replay.write_bytes(b"replay")
        self.default = self.root / "default.json"
        self.localized = self.root / "localized.json"
        self.custom = self.root / "custom.json"
        for path, contents in (
            (self.default, b"default"),
            (self.localized, b"localized"),
            (self.custom, b"custom"),
        ):
            path.write_bytes(contents)
        self.sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.launcher = self.root / "launcher.py"
        self.launcher.touch()

    def invoke(self, options=(), *, names=None):
        captured = {}

        def intercept(executable, argv, environment):
            captured.update(executable=executable, argv=argv, environment=environment)
            raise ExecIntercept

        profiles = (
            names
            if names is not None
            else {
                "default": (self.default, self.sha(self.default)),
                "localized": (self.localized, self.sha(self.localized)),
            }
        )
        with (
            patch.object(entry, "BUILTIN_PROFILES", profiles),
            patch.object(entry, "LAUNCHER", self.launcher),
            patch("sys.argv", [str(ENTRY), str(self.replay), *options]),
            patch.dict(os.environ, {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}),
            patch.object(entry.os, "execve", side_effect=intercept),
            self.assertRaises(ExecIntercept),
        ):
            entry.main()
        return captured

    def test_builtin_localized_forwards_exact_profile_hash_and_headless_environment(self):
        result = self.invoke(("--profile-name", "localized"))
        args = result["argv"]
        self.assertEqual(args[args.index("--profile") + 1], str(self.localized))
        self.assertEqual(args[args.index("--profile-sha256") + 1], self.sha(self.localized))
        self.assertNotIn("DISPLAY", result["environment"])
        self.assertNotIn("WAYLAND_DISPLAY", result["environment"])

    def test_default_and_explicit_custom_profiles(self):
        for options, profile in (
            ((), self.default),
            (
                ("--profile", str(self.custom), "--profile-sha256", self.sha(self.custom)),
                self.custom,
            ),
        ):
            with self.subTest(profile=profile):
                args = self.invoke(options)["argv"]
                self.assertEqual(args[args.index("--profile") + 1], str(profile))
                self.assertEqual(args[args.index("--profile-sha256") + 1], self.sha(profile))

    def test_automatic_taunt_profile_only_for_implicit_default(self):
        args = self.invoke()["argv"]
        self.assertEqual(args[args.index("--taunt-profile") + 1], str(self.localized))
        self.assertEqual(args[args.index("--taunt-profile-sha256") + 1], self.sha(self.localized))
        for options in (
            ("--profile-name", "default"),
            ("--profile-name", "localized"),
            ("--profile", str(self.custom), "--profile-sha256", self.sha(self.custom)),
        ):
            with self.subTest(options=options):
                self.assertNotIn("--taunt-profile", self.invoke(options)["argv"])

    def test_mismatched_builtin_hash_fails_before_exec(self):
        names = {
            "default": (self.default, self.sha(self.default)),
            "localized": (self.localized, "0" * 64),
        }
        with (
            patch.object(entry, "BUILTIN_PROFILES", names),
            patch.object(entry, "LAUNCHER", self.launcher),
            patch("sys.argv", [str(ENTRY), str(self.replay), "--profile-name", "localized"]),
            patch.object(entry.os, "execve") as launch,
        ):
            with self.assertRaises(SystemExit) as error:
                entry.main()
            self.assertEqual(error.exception.code, 2)
            launch.assert_not_called()

    def test_named_and_custom_profiles_cannot_be_combined(self):
        with (
            patch(
                "sys.argv",
                [
                    str(ENTRY),
                    str(self.replay),
                    "--profile-name",
                    "localized",
                    "--profile",
                    str(self.custom),
                    "--profile-sha256",
                    self.sha(self.custom),
                ],
            ),
            patch.object(entry.os, "execve") as launch,
        ):
            with self.assertRaises(SystemExit) as error:
                entry.main()
            self.assertEqual(error.exception.code, 2)
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
