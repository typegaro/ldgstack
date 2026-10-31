"""Tests for the read-only dashboard server (tracker_ui)."""
from __future__ import annotations

import http.client
import json
import sys
import threading
import unittest
from pathlib import Path

from test_workflow import FEATURE, PLUGIN, CliTestCase, spec_text

sys.path.insert(0, str(PLUGIN / "skills" / "spec-tracker" / "scripts"))

from tracker_ui import server  # noqa: E402


class DashboardTest(CliTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_spec("0001-second.md", spec_text(1, "second", depends_on=[0], body="# Second\n\n- **R1** Does <b>things</b> per 0000.\n"))
        self.start()
        self.httpd = server.make_server(self.root, 0, "127.0.0.1")
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.stopping = True
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        super().tearDown()

    def request(self, path: str, method: str = "GET") -> tuple[int, bytes, http.client.HTTPResponse]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body, response

    def get(self, path: str) -> dict:
        status, body, _ = self.request(path)
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def test_index_and_static_files(self) -> None:
        for path, marker in (("/", b"spec-workflow"), ("/app.js", b"use strict"), ("/app.css", b"--bg")):
            status, body, _ = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn(marker, body)
        self.assertEqual(self.request("/server.py")[0], 404)
        self.assertEqual(self.request("/static/../server.py")[0], 404)

    def test_prs_lists_the_open_record(self) -> None:
        data = self.get("/api/prs")
        row = next(item for item in data["prs"] if item["feature"] == FEATURE)
        self.assertEqual((row["state"], row["stage"], row["spec_id"]), ("open", "implementing", "0000"))
        self.assertEqual(row["requirements"], {"total": 1, "implemented": 1, "tested": 0})
        self.assertEqual(row["bugs"]["open"], 0)
        self.assertIn("pr_status_available", data)

    def test_queues_degrade_without_queue_status(self) -> None:
        data = self.get("/api/queues")
        self.assertEqual(set(data["queues"]), {"review", "test", "merge"})
        self.assertIsInstance(data["agents"], list)
        self.assertIn("merged_today", data["counters"])
        if not data["available"]:
            self.assertEqual(data["source"], "records")

    def test_specs_pipeline(self) -> None:
        data = self.get("/api/specs")
        self.assertEqual({row["id"] for row in data["specs"]}, {0, 1})
        self.assertEqual(sum(data["stages"].values()), 2)
        self.assertEqual(data["stages"]["implementing"], 1)
        self.assertIn("feature", data["kinds"])
        second = next(row for row in data["specs"] if row["id"] == 1)
        self.assertEqual(second["depends_on"], [0])

    def test_spec_reader_data(self) -> None:
        data = self.get("/api/spec/0001")
        self.assertEqual(data["spec"]["feature"], "0001-second")
        self.assertIn("<b>things</b>", data["body"])
        self.assertNotIn("depends_on", data["body"])
        self.assertEqual([item["id"] for item in data["links"]["depends_on"]], [0])
        self.assertTrue(any(item["relation"] == "self" for item in data["effective"]))
        self.assertEqual(data["lifecycle"][0]["name"], "Draft")
        self.assertEqual(self.get("/api/spec/0000")["requirements"], {})  # marks need `N:Rn` spec refs
        self.assertEqual(self.request("/api/spec/0099")[0], 404)

    def test_record_detail(self) -> None:
        data = self.get(f"/api/record/{FEATURE}")
        self.assertEqual(data["pr"]["feature"], FEATURE)
        self.assertEqual(data["requirements"][0]["id"], "REQ-001")
        self.assertEqual([item["name"] for item in data["checks"]], ["unit"])
        self.assertTrue(data["timeline"])
        self.assertEqual(data["timeline"][0]["kind"], "created")
        self.assertEqual(set(data["sidebar"]), {"running", "bugs_by_status", "bugs_by_finder", "batches", "reviews", "fixes", "open_seconds", "depends_on"})
        self.assertEqual(self.request("/api/record/0042-missing")[0], 404)

    def test_activity_and_meta(self) -> None:
        events = self.get("/api/activity")["events"]
        self.assertTrue(any(item["feature"] == FEATURE for item in events))
        meta = self.get("/api/meta")
        self.assertEqual(meta["project"], Path(self.root).name)

    def test_path_traversal_and_bad_ids_are_refused(self) -> None:
        for path in ("/api/spec/..%2f..%2fetc%2fpasswd", "/api/record/..%2fspecs%2f0000-demo", "/api/record/../../x", "/api/spec/%2e%2e",
                     "/api/spec/0000-DEMO", "/api/record/0000-demo%00", "/api/spec/1;ls"):
            self.assertIn(self.request(path)[0], (400, 404), path)
        self.assertEqual(self.request("/api/spec/..%2f..%2fetc%2fpasswd")[0], 400)
        self.assertEqual(self.request("/api/nope")[0], 404)

    def test_read_only(self) -> None:
        before = {path: path.stat().st_mtime_ns for path in self.root.rglob("*") if path.is_file()}
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            self.assertEqual(self.request("/api/prs", method)[0], 405)
        for path in ("/api/prs", "/api/queues", "/api/specs", "/api/spec/0000", f"/api/record/{FEATURE}", "/api/activity"):
            self.get(path)
        after = {path: path.stat().st_mtime_ns for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_event_stream_handshake_and_change(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        connection.request("GET", "/api/events")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "text/event-stream")
        lines = [response.fp.readline().decode() for _ in range(3)]
        self.assertIn("event: hello\n", lines)
        self.write_spec("0002-third.md", spec_text(2, "third"))
        seen = ""
        for _ in range(12):
            seen += response.fp.readline().decode()
            if "event: change" in seen:
                break
        self.assertIn("event: change", seen)
        connection.close()


class HelperTest(unittest.TestCase):
    def test_ids_of_accepts_mixed_shapes(self) -> None:
        self.assertEqual(server.ids_of([1, {"id": 2}, [3, {"id": 4}], "x", True]), [1, 2, 3, 4])

    def test_time_helpers(self) -> None:
        self.assertEqual(server.seconds_between("2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"), 3600)
        self.assertIsNone(server.seconds_between("nope", None))


if __name__ == "__main__":
    unittest.main()
