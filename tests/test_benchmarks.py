#!/usr/bin/env python3
"""The with/without-skill benchmark (#677): its checkers, its results files, its page and its runner.

No model is called here. The checkers are graded on a known-good output (an ffmpeg command that
does the request) and a known-bad one (the input unchanged); the runner is run with --dry-run and
against an endpoint on 127.0.0.1 that answers with one fixed tool call.
"""
import concurrent.futures
import copy
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks"
sys.path.insert(0, str(BENCH))
import page  # noqa: E402
import tasks  # noqa: E402


def env_without_endpoint():
    return {k: v for k, v in os.environ.items() if not k.startswith("BENCH_")}


class CheckerTests(unittest.TestCase):
    def test_every_checker_passes_a_correct_output_and_fails_the_input(self):
        """A checker that passes everything grades nothing: each one is shown the output an ffmpeg
        command writes for its request, which must pass, and the input copied to the output name,
        which must fail."""
        def one(task):
            with tempfile.TemporaryDirectory() as work:
                tasks.make_fixtures(task["inputs"], work)
                made = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", *task["reference"], task["output"]],
                                      cwd=work, capture_output=True, text=True)
                good = tasks.grade(task, work) if made.returncode == 0 else (None, made.stderr[-300:])
                Path(work, task["output"]).unlink(missing_ok=True)
                shutil.copy(Path(work) / task["inputs"][0], Path(work) / task["output"])
                return task["id"], good, tasks.grade(task, work)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(2, min(8, os.cpu_count() or 2))) as pool:
            results = list(pool.map(one, tasks.TASKS))
        for tid, good, bad in results:
            with self.subTest(task=tid):
                if good[0] is None and "No such filter: 'subtitles'" in good[1]:
                    continue  # this ffmpeg has no libass to write the correct output with; the bad one is still graded
                self.assertTrue(good[0], good[1])
        for tid, good, bad in results:
            with self.subTest(task=tid, output="the input unchanged"):
                self.assertFalse(bad[0], bad[1])

    def test_the_set_is_24_requests_each_naming_its_output_and_inputs(self):
        self.assertEqual(len(tasks.TASKS), 24)
        self.assertEqual(len(tasks.BY_ID), 24)
        for t in tasks.TASKS:
            with self.subTest(task=t["id"]):
                self.assertIn(t["output"], t["request"])
                for name in t["inputs"]:
                    self.assertIn(name, t["request"])
                    self.assertTrue(name in tasks.FIXTURES or name in tasks.TEXT_FIXTURES)
        # the requests the 2026-11-21 benchmark named are in the set (#633, #670, #684)
        self.assertLessEqual({"cut", "resize", "vertical", "mute", "fade", "join", "captions", "loudness", "reel", "silence"}, set(tasks.BY_ID))

    def test_a_missing_or_unreadable_output_is_a_fail_not_a_crash(self):
        with tempfile.TemporaryDirectory() as work:
            self.assertEqual(tasks.grade(tasks.BY_ID["cut"], work), (False, "out.mp4 was not written"))
            Path(work, "out.mp4").write_text("not a video")
            ok, detail = tasks.grade(tasks.BY_ID["cut"], work)
            self.assertFalse(ok)
            self.assertIn("no readable video", detail)


class ResultsTests(unittest.TestCase):
    def test_every_results_file_is_valid_and_the_page_is_what_they_give(self):
        docs = page.load()
        self.assertTrue(docs)
        for name, doc in docs:
            with self.subTest(file=name):
                # a figure not run here names the issue or PR it was published in
                if doc["source"] != "benchmarks/run.py":
                    self.assertTrue(doc["source"].startswith("https://github.com/kajisho5/ffmpeg-skill/"))
                    self.assertTrue(doc["note"])
                self.assertTrue(name.startswith(doc["date"] + "_" + doc["release"] + "_"))
                self.assertTrue(name.endswith("_" + doc["arm"] + ".json"))
        self.assertEqual((ROOT / "docs" / "benchmark.md").read_text(encoding="utf-8"), page.render(),
                         "run python3 benchmarks/page.py --write")
        # the published figures the page carries, as #633, #670, #677 and #684 state them
        by_name = dict(docs)
        self.assertEqual([(by_name[f]["correct"], by_name[f]["calls_per_request"]) for f in (
            "2026-11-21_4.3.4_three-small-models_skill.json", "2026-11-21_4.3.4_three-small-models_raw.json",
            "2026-11-21_4.4.0_three-small-models_skill.json", "2026-11-21_4.4.1_three-small-models_skill.json")],
            [(63, 11.1), (66, 7.0), (69, 9.4), (71, 6.5)])

    def test_the_schema_refuses_what_a_page_would_misreport(self):
        _, good = page.load()[0]
        page.validate(good)
        for change, why in ((lambda d: d.pop("correct"), "no `correct`"),
                            (lambda d: d.update(correct=d["requests"] + 1), "outside 0..requests"),
                            (lambda d: d.update(correct=None, calls_per_request=None), "neither"),
                            (lambda d: d.update(arm="none"), "neither skill nor raw"),
                            (lambda d: d.update(date="21/11/2026"), "YYYY-MM-DD"),
                            (lambda d: d.update(source="a blog post"), "neither benchmarks/run.py"),
                            (lambda d: d.update(extra=1), "not a field"),
                            (lambda d: d.update(correct=True), "`correct` is bool"),
                            (lambda d: d.update(source="benchmarks/run.py"), "lists every run")):
            doc = copy.deepcopy(good)
            change(doc)
            with self.subTest(why=why):
                with self.assertRaises(page.Invalid) as e:
                    page.validate(doc)
                self.assertIn(why, str(e.exception))


class RunnerTests(unittest.TestCase):
    RUN = [sys.executable, str(BENCH / "run.py")]

    def test_dry_run_lists_the_tasks_and_the_requests_with_no_endpoint(self):
        proc = subprocess.run(self.RUN + ["some-model", "--arm", "skill", "--runs", "1", "--dry-run"],
                              capture_output=True, text=True, env=env_without_endpoint(), timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([r["task"] for r in rows], [t["id"] for t in tasks.TASKS])
        for r in rows:
            self.assertEqual(r["body"]["model"], "some-model")
            self.assertEqual([t["function"]["name"] for t in r["body"]["tools"]], ["bash"])
            self.assertEqual(r["body"]["messages"][1]["content"], tasks.BY_ID[r["task"]]["request"])
            self.assertTrue(all(c.startswith("ffmpeg ") or c.startswith("write ") for c in r["inputs"]))
        self.assertIn("characters, SKILL.md included)", rows[0]["body"]["messages"][0]["content"])
        raw = subprocess.run(self.RUN + ["m", "--arm", "raw", "--only", "cut,mute", "--dry-run"],
                             capture_output=True, text=True, env=env_without_endpoint(), timeout=60)
        rows = [json.loads(line) for line in raw.stdout.splitlines()]
        self.assertEqual([r["task"] for r in rows], ["cut", "mute"])
        self.assertNotIn("SKILL.md", rows[0]["body"]["messages"][0]["content"])
        bad = subprocess.run(self.RUN + ["m", "--arm", "raw", "--only", "cutt", "--dry-run"], capture_output=True, text=True, timeout=60)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("unknown task id(s): cutt", bad.stderr)
        # without an endpoint, a real run says what to set and calls nothing
        none = subprocess.run(self.RUN + ["m", "--arm", "raw", "--only", "cut"], capture_output=True, text=True,
                              env=env_without_endpoint(), timeout=60)
        self.assertEqual(none.returncode, 2)
        self.assertIn("BENCH_API_URL and BENCH_API_KEY", none.stderr)

    def test_a_run_against_a_local_endpoint_is_graded_by_measurement(self):
        """An endpoint on 127.0.0.1 answers the first request with one bash call that does the cut and
        the second with a claim. The results file counts the call, grades the file it measured, keeps
        the claim beside it, and passes the schema; the key went in the header and nowhere else."""
        seen = []

        class Endpoint(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((self.headers.get("Authorization"), body))
                done = any(m["role"] == "tool" for m in body["messages"])
                msg = ({"role": "assistant", "content": "Wrote out.mp4, 4 s long."} if done else
                       {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {
                           "name": "bash", "arguments": json.dumps({"command": "ffmpeg -v error -ss 2 -i ramp.mp4 -t 4 out.mp4"})}}]})
                data = json.dumps({"choices": [{"message": msg}], "usage": {"prompt_tokens": 1000, "completion_tokens": 10, "cost": 0.001}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env = dict(env_without_endpoint(), BENCH_API_URL=f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                           BENCH_API_KEY="test-key", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
                proc = subprocess.run(self.RUN + ["local-model", "--arm", "raw", "--runs", "1", "--only", "cut",
                                                  "--results", str(Path(tmp) / "results"), "--out", str(Path(tmp) / "t")],
                                      capture_output=True, text=True, env=env, timeout=300)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                [path] = (Path(tmp) / "results").glob("*.json")
                doc = page.validate(json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(path.name.split("_")[2:], ["local-model", "raw.json"])
                self.assertEqual((doc["correct"], doc["requests"], doc["calls_per_request"], doc["cost_usd"]), (1, 1, 1, 0.002))
                self.assertEqual(doc["task_set"], "common-24:cut")
                self.assertEqual(doc["runs"][0]["claimed"], "Wrote out.mp4, 4 s long.")
                self.assertIn("first frame level", doc["runs"][0]["detail"])
                transcript = json.loads((Path(tmp) / "t" / "cut-0" / "transcript.json").read_text(encoding="utf-8"))
                self.assertEqual(transcript[-2]["role"], "tool")
                self.assertTrue(transcript[-2]["content"].startswith("exit code 0"))
                self.assertNotIn("test-key", path.read_text(encoding="utf-8") + json.dumps(transcript))
                # #684's question, where the calls go, is answered from the same transcripts
                where = subprocess.run([sys.executable, str(BENCH / "calls.py"), str(Path(tmp) / "t"), str(Path(tmp) / "t")],
                                       capture_output=True, text=True, timeout=60)
                self.assertRegex(where.stdout, r"^cut +1\.0 calls +\[raw ffmpeg 1\.0\] +vs +1\.0 +\[raw ffmpeg 1\.0\] +\+0\.0$")
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual({auth for auth, _ in seen}, {"Bearer test-key"})
        self.assertEqual(len(seen), 2)

    def test_an_endpoint_that_refuses_every_call_writes_no_results(self):
        """A wrong key is not 0 of N correct: nothing was measured, so no results file is written."""
        class Refuse(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(401)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"no")

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Refuse)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env = dict(env_without_endpoint(), BENCH_API_URL=f"http://127.0.0.1:{server.server_port}/v1", BENCH_API_KEY="wrong",
                           NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
                proc = subprocess.run(self.RUN + ["m", "--arm", "raw", "--runs", "1", "--only", "mute", "--results", tmp, "--out", tmp],
                                      capture_output=True, text=True, env=env, timeout=120)
                self.assertEqual(proc.returncode, 1, proc.stderr)
                self.assertIn("HTTP 401", proc.stderr)
                self.assertEqual(list(Path(tmp).glob("*.json")), [])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
