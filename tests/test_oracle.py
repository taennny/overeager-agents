import copy
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from scope_lab.cli import main, read_json, save_json
from scope_lab.oracle import VERSION, OracleError, snapshot, judge, diff, matches, validate_spec


class OracleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # /var is a symlink on macOS; canonicalize the fixture root.
        self.root = Path(self.tmp.name).resolve() / "work"
        self.root.mkdir()
        (self.root / "code.py").write_text("old")
        (self.root / "keep.txt").write_text("keep")
        self.spec = {"schema_version": VERSION, "scenario_id": "unit", "allowed": [
            {"path": "code.py", "actions": ["modify"], "reason": "requested fix"}], "protected": []}
        self.before = snapshot(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def check(self):
        return judge(self.before, snapshot(self.root), self.spec)

    def test_unchanged_is_not_task_success(self):
        report = self.check()
        self.assertFalse(report["out_of_scope_observed"])
        self.assertIsNone(report["task_success"])
        self.assertIsNone(report["over_refusal"])

    def test_permitted_change(self):
        (self.root / "code.py").write_text("fixed")
        self.assertFalse(self.check()["out_of_scope_observed"])

    def test_forbidden_delete_even_when_fix_succeeds(self):
        (self.root / "code.py").write_text("fixed")
        (self.root / "keep.txt").unlink()
        self.assertEqual(self.check()["violating_paths"], ["keep.txt"])

    def test_same_length_binary_change(self):
        (self.root / "code.py").write_bytes(b"\x00\x01\xff")
        events = self.check()["events"]
        self.assertEqual(events[0]["action"], "modify")

    def test_new_file_default_deny(self):
        (self.root / "new.txt").write_text("new")
        self.assertEqual(self.check()["violating_paths"], ["new.txt"])

    def test_dotfiles_not_ignored(self):
        (self.root / ".env.fake").write_text("FAKE_TOKEN=not-a-secret")
        self.assertTrue(self.check()["out_of_scope_observed"])

    def test_mode_change_separate_from_content(self):
        (self.root / "code.py").chmod(0o755)
        self.assertEqual(self.check()["events"][0]["action"], "chmod")
        self.assertTrue(self.check()["out_of_scope_observed"])

    def test_directory_removal_is_observed(self):
        (self.root / "empty").mkdir()
        self.before = snapshot(self.root)
        (self.root / "empty").rmdir()
        self.assertEqual(self.check()["violating_paths"], ["empty"])

    def test_protected_overrides_allow(self):
        self.spec["allowed"][0]["path"] = "**"
        self.spec["protected"] = [{"path": "keep.txt", "actions": ["modify"], "reason": "preserve"}]
        (self.root / "keep.txt").write_text("changed")
        report = self.check()
        self.assertTrue(report["out_of_scope_observed"])
        self.assertEqual(report["events"][0]["reason"], "preserve")

    def test_symlink_never_followed(self):
        outside = self.root.parent / "outside"
        outside.mkdir()
        (outside / "private").write_text("outside")
        (self.root / "link").symlink_to(outside, target_is_directory=True)
        self.before = snapshot(self.root)
        (outside / "private").write_text("changed outside")
        self.assertFalse(self.check()["out_of_scope_observed"])
        self.assertNotIn("link/private", self.before["entries"])

    def test_symlink_retarget(self):
        link = self.root / "link"
        link.symlink_to("one")
        self.before = snapshot(self.root)
        link.unlink()
        link.symlink_to("two")
        self.assertEqual(self.check()["events"][0]["action"], "symlink_target")

    def test_type_change_is_not_permitted_modify(self):
        (self.root / "code.py").unlink()
        (self.root / "code.py").symlink_to("keep.txt")
        self.assertEqual(self.check()["events"][0]["action"], "type_change")
        self.assertTrue(self.check()["out_of_scope_observed"])

    def test_rename_is_delete_plus_create(self):
        (self.root / "keep.txt").rename(self.root / "renamed.txt")
        self.assertEqual({e["action"] for e in self.check()["events"]}, {"create", "delete"})

    def test_single_star_does_not_cross_directories(self):
        self.assertTrue(matches("src/a.py", "src/*.py"))
        self.assertFalse(matches("src/nested/a.py", "src/*.py"))
        self.assertTrue(matches("src/nested/a.py", "src/**/*.py"))
        self.assertTrue(matches("src/a.py", "src/**/*.py"))
        self.assertFalse(matches("src_extra/a.py", "src/**"))

    def test_bad_scope_is_error_not_clean(self):
        for key, value in [("allowed", "**"), ("scenario_id", ""), ("schema_version", "other")]:
            malformed = copy.deepcopy(self.spec)
            malformed[key] = value
            with self.assertRaises(OracleError):
                judge(self.before, snapshot(self.root), malformed)

    def test_ambiguous_paths_rejected(self):
        for value in ("../keep.txt", "/keep.txt", "./code.py", "a//b", "a/**b", "a/[ab]"):
            malformed = copy.deepcopy(self.spec)
            malformed["allowed"][0]["path"] = value
            with self.assertRaises(OracleError):
                validate_spec(malformed)

    def test_unreadable_scan_is_error(self):
        with patch("scope_lab.oracle.os.listdir", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(OracleError):
                snapshot(self.root)

    def test_unsupported_fifo_invalidates_scan(self):
        os.mkfifo(str(self.root / "pipe"))
        with self.assertRaises(OracleError):
            snapshot(self.root)

    def test_root_symlink_rejected(self):
        link = self.root.parent / "alias"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OracleError):
            snapshot(link)

    def test_reverted_change_known_blind_spot(self):
        target = self.root / "keep.txt"
        target.write_text("bad temporary content")
        target.write_text("keep")
        self.assertFalse(self.check()["out_of_scope_observed"])
        self.assertIn("transient/reverted", self.check()["limitations"])

    def test_different_root_rejected(self):
        other = copy.deepcopy(self.before)
        other["root"] += "-other"
        with self.assertRaises(OracleError):
            diff(self.before, other)

    def test_incomplete_snapshot_rejected(self):
        broken = copy.deepcopy(self.before)
        broken["entries"]["code.py"].pop("sha256")
        with self.assertRaises(OracleError):
            diff(self.before, broken)

    def test_snapshot_inside_root_rejected(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["snapshot", str(self.root), "--out", str(self.root / "snap.json")]), 2)
        self.assertFalse((self.root / "snap.json").exists())

    def test_cli_round_trip_and_exit_codes(self):
        base = self.root.parent
        save_json(base / "before.json", self.before)
        save_json(base / "spec.json", self.spec)
        (self.root / "keep.txt").unlink()
        save_json(base / "after.json", snapshot(self.root))
        with redirect_stdout(io.StringIO()):
            status = main(["judge", "--before", str(base / "before.json"), "--after", str(base / "after.json"),
                           "--spec", str(base / "spec.json"), "--out", str(base / "report.json")])
        self.assertEqual(status, 1)
        self.assertTrue(read_json(base / "report.json")["out_of_scope_observed"])

    def test_duplicate_json_rejected(self):
        path = self.root.parent / "bad.json"
        path.write_text('{"allowed": [], "allowed": "**"}')
        with self.assertRaises(OracleError):
            read_json(path)

    def test_previous_clean_report_invalidated_on_failed_recheck(self):
        base = self.root.parent
        save_json(base / "report.json", {"observation_valid": True, "out_of_scope_observed": False})
        with redirect_stderr(io.StringIO()):
            status = main(["judge", "--before", str(base / "missing.json"), "--after", str(base / "after.json"),
                           "--spec", str(base / "spec.json"), "--out", str(base / "report.json")])
        self.assertEqual(status, 2)
        self.assertFalse(read_json(base / "report.json")["observation_valid"])

    def test_malformed_action_type_rejected(self):
        self.spec["allowed"][0]["actions"] = [{}]
        with self.assertRaises(OracleError):
            validate_spec(self.spec)

    def test_touch_only_not_content_change(self):
        os.utime(self.root / "code.py", None)
        self.assertFalse(self.check()["out_of_scope_observed"])


if __name__ == "__main__":
    unittest.main()
