"""Runs export_comments.py against a local mock of the okdata API. No network, no real key."""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
os.environ["NO_PROXY"] = "*"

import export_comments as tool  # noqa: E402
from mock_okdata import TEST_KEY, MockOkdata, error, ok  # noqa: E402

VID = "7305085486984858894"


def comment(i: int) -> dict:
    return {"id": f"c{i}", "post_id": VID, "parent_id": None, "text": f"comment, \"{i}\"", "likes": i, "replies": 0,
            "published_at": "2026-11-01T00:00:00Z", "author": {"id": "u", "username": "fan", "name": "Fan"}, "ip_location": None}


class ExportCommentsTest(unittest.TestCase):
    def setUp(self) -> None:
        pages = {None: ok("c", items=[comment(1), comment(2)], next_cursor="p2"), "p2": ok("c", items=[comment(3)], next_cursor="p3"),
                 "p3": ok("c", items=[comment(4)])}
        self.api = MockOkdata({
            "/v1/tiktok/videos/comments/list": lambda q: (404, error("not_found")) if q["id"] == "7000000000000000000"
            else (200, pages[q.get("cursor")]),
            "/v1/tiktok/videos/get": lambda q: (200, ok("g", item={"id": VID})),
        })
        tool.API = self.api.url
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.api.close()
        self.tmp.cleanup()

    def run_tool(self, *argv: str, key: str = TEST_KEY) -> tuple:
        os.environ["OKDATA_API_KEY"] = key
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = tool.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_csv_from_a_full_link_follows_pages(self) -> None:
        code, out, log = self.run_tool(f"https://www.tiktok.com/@a/video/{VID}?lang=en", "--pages", "2")
        self.assertEqual(code, 0, log)
        rows = list(csv.DictReader(io.StringIO(out)))
        self.assertEqual([r["comment_id"] for r in rows], ["c1", "c2", "c3"])  # stopped at 2 pages
        self.assertEqual(rows[0]["text"], 'comment, "1"')
        self.assertEqual([r["query"].get("cursor") for r in self.api.paid()], [None, "p2"])
        self.assertIn("spent $0.004", log)

    def test_short_link_is_resolved_and_jsonl_written_to_file(self) -> None:
        target = Path(self.tmp.name) / "c.jsonl"
        code, _, log = self.run_tool("https://vm.tiktok.com/ZMabc123/", "--pages", "5", "--format", "jsonl", "-o", str(target))
        self.assertEqual(code, 0, log)
        lines = [json.loads(x) for x in target.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 4)
        self.assertEqual(self.api.paid()[0]["path"], "/v1/tiktok/videos/get")
        self.assertIn("1 short-link lookup", log)

    def test_one_bad_video_is_skipped(self) -> None:
        code, out, log = self.run_tool("7000000000000000000", VID, "--pages", "1")
        self.assertEqual(code, 0)
        self.assertIn("skipped 7000000000000000000: not_found", log)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(out)))), 2)

    def test_budget_dry_run_and_missing_key(self) -> None:
        self.assertEqual(self.run_tool(VID, "--pages", "1000")[0], 3)
        code, _, log = self.run_tool(VID, "--dry-run", key="")
        self.assertEqual(code, 0)
        self.assertIn("at most $0.004", log)
        code, _, log = self.run_tool(VID, key="")
        self.assertEqual(code, 2)
        self.assertIn("src=gh-tiktok-comments-export", log)
        self.assertEqual(self.api.paid(), [])

    def test_wrong_key_stops_the_run(self) -> None:
        code, _, log = self.run_tool(VID, VID, key="okd_wrong")
        self.assertEqual(code, 1)
        self.assertIn("stopped: unauthorized", log)
        self.assertEqual(len(self.api.paid()), 1)

    def test_rejects_things_that_are_not_videos(self) -> None:
        code, _, log = self.run_tool("hello world", "--pages", "1")
        self.assertIn("skipped hello world: invalid_params", log)
        self.assertEqual(self.api.paid(), [])

    def test_a_failed_run_keeps_the_previous_export(self) -> None:
        target = Path(self.tmp.name) / "old.csv"
        target.write_text("previous export\n", encoding="utf-8")
        code, _, _ = self.run_tool(VID, "-o", str(target), key="okd_wrong")
        self.assertEqual(code, 1)
        self.assertEqual(target.read_text(encoding="utf-8"), "previous export\n")
        self.assertFalse(Path(f"{target}.part").exists())

    def test_formula_like_comments_are_neutralised_in_csv(self) -> None:
        self.api.routes["/v1/tiktok/videos/comments/list"] = lambda q: (200, ok("c", items=[{**comment(1), "text": "=1+1", "author": {"username": "@fan"}}]))
        _, out, _ = self.run_tool(VID, "--pages", "1")
        row = next(csv.DictReader(io.StringIO(out)))
        self.assertEqual((row["text"], row["author_username"]), ("'=1+1", "'@fan"))

    def test_uses_live_prices_for_the_plan(self) -> None:
        self.api.prices = {"tiktok.videos.comments.list": "0.5", "tiktok.videos.get": "0.5"}
        code, _, log = self.run_tool(VID, "--pages", "3")
        self.assertEqual(code, 3)  # 1.5 > the default $1 budget
        self.assertIn("at most $1.5", log)


if __name__ == "__main__":
    unittest.main()
