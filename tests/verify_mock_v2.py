"""Regression tests for public contracts, hard deadlines and concurrent CLI runs."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
(PACKAGE / "work").mkdir(exist_ok=True)
TEMP = tempfile.TemporaryDirectory(prefix="mock-v2-", dir=PACKAGE / "work")
STATE = Path(TEMP.name) / "run"
CLI = PACKAGE / "mock/cli.py"
subprocess.run([sys.executable, "-X", "utf8", str(CLI), "prepare", "--out", str(STATE)],
               check=True, capture_output=True)
os.environ["NARAE_BENCH_STATE"] = str(STATE)
sys.path.insert(0, str(PACKAGE / "mock"))
from mock_workflow import World, CATALOG


def world(case_id):
    return World(next(c for c in CATALOG if c["id"] == case_id))


def results(case_id):
    return next(r for r in json.loads((STATE / "results.json").read_text(encoding="utf-8"))["results"]
                if r["case_id"] == case_id)


class Contracts(unittest.TestCase):
    def test_circulation_accepts_observed_locations_and_rejects_invented_sources(self):
        for sources, expected in [(["CIRC-01"], True), (["CIRC-01:p1", "CIRC-01:table.r3"], True),
                                  (["CIRC-01:invented"], False), (["DOC-OTHER:p1"], False), ([], False)]:
            w = world("NP-E-06")
            for tool, args in w.oracle[:-1]:
                w.call(tool, copy.deepcopy(args))
            w.call("finish", {**w.gold, "sources": sources})
            self.assertEqual(w.grade()["K4"], expected, sources)

    def test_chat_without_requested_title_requires_actual_empty_title(self):
        w = world("CBE-06")
        self.assertEqual(w.gold["title"], "")
        for tool, args in w.oracle:
            w.call(tool, copy.deepcopy(args))
        self.assertTrue(all(w.grade().values()))
        w.call("finish", {**w.gold, "title": "가상 알림"})
        self.assertFalse(w.grade()["K2"])

    def test_new_recipient_is_searchable_and_room_creation_is_reported(self):
        w = world("CBE-05")
        found = w.call("cbe.search", {"name": "가상최", "scope": "auto"})
        self.assertEqual([u["id"] for u in found["users"]], ["U-NEW"])
        self.assertEqual(found["searched"], ["my", "all"])
        for tool, args in w.oracle[:-1]:
            answer = w.call(tool, copy.deepcopy(args))
        self.assertTrue(answer["new_room_created"])
        self.assertEqual(answer["new_rooms"], ["ROOM-NEW"])

    def test_concurrent_cases_merge_and_same_case_cannot_run_twice(self):
        processes = []
        try:
            for case_id in ("NP-P-01", "NP-P-02"):
                p = subprocess.Popen([sys.executable, "-X", "utf8", str(CLI), "run", "--state", str(STATE), "--case", case_id],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8")
                processes.append((case_id, p))
                self.assertEqual(json.loads(p.stdout.readline())["event"], "task")
            duplicate = subprocess.run([sys.executable, "-X", "utf8", str(CLI), "run", "--state", str(STATE), "--case", "NP-P-01"],
                                       input="", capture_output=True, text=True, encoding="utf-8", timeout=5)
            self.assertEqual(duplicate.returncode, 2)
            self.assertIn("already running", duplicate.stderr)
            for case_id, p in processes:
                payload = "".join(json.dumps({"tool": t, "args": a}) + "\n" for t, a in world(case_id).oracle)
                out, err = p.communicate(payload, timeout=5)
                self.assertEqual(p.returncode, 0, err)
                self.assertEqual(json.loads(out.splitlines()[-1])["event"], "closed")
            self.assertEqual(results("NP-P-01")["status"], "PASS")
            self.assertEqual(results("NP-P-02")["status"], "PASS")
        finally:
            for _, p in processes:
                if p.poll() is None:
                    p.kill()
                p.communicate()

    def test_silent_or_partial_line_input_cannot_hold_session_open(self):
        for case_id, partial in [("NP-P-05", ""), ("NP-E-01", '{"tool":')]:
            # Shorten only this test process's catalog; production budgets stay fixed.
            script = ("import sys; from pathlib import Path; from types import SimpleNamespace; "
                      f"sys.path.insert(0,{str(PACKAGE / 'mock')!r}); import cli; "
                      f"_,catalog,_=cli.load_world(Path({str(STATE)!r})); "
                      f"next(c for c in catalog if c['id']=={case_id!r})['timeout_minutes']=0.005; "
                      f"cli.run_case(SimpleNamespace(state={str(STATE)!r},case={case_id!r}))")
            p = subprocess.Popen([sys.executable, "-X", "utf8", "-c", script], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            try:
                self.assertEqual(json.loads(p.stdout.readline())["event"], "task")
                if partial:
                    p.stdin.write(partial)
                    p.stdin.flush()
                p.wait(timeout=4)  # Keep stdin OPEN: deadline must end the process.
                self.assertEqual(p.returncode, 0, p.stderr.read())
                self.assertEqual(results(case_id)["failure_layer"], "TIMEOUT")
            finally:
                if p.poll() is None:
                    p.kill()
                p.communicate()


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        TEMP.cleanup()
