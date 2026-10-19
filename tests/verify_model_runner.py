"""HTTP/stdio bridge regressions with scripted responses, never model scores."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import importlib.util
import io
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
(ROOT / "work").mkdir(exist_ok=True)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="model-bridge-", dir=ROOT / "work")
        self.out = Path(self.temp.name) / "run"
        self.calls = []
        self.mode = "success"
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def emit(self, value, status=200):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(value, ensure_ascii=False).encode("utf-8"))

            def do_GET(self):
                self.emit({"data": [{"id": "scripted-test-fixture"}]})

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.calls.append(request)
                if owner.mode == "failure":
                    return self.emit({"error": "test failure"}, 503)
                if owner.mode == "invalid":
                    text = "not JSON\nsecond line"
                elif owner.mode == "note":
                    task = json.loads(request["messages"][1]["content"])
                    if len(owner.calls) == 1:
                        reply = {"tool": "cbe.send", "args": {"kind": "note", "recipient_id": task["initial_observation"]["allowed_recipient"]["id"],
                                 "title": "가상 알림", "body": "가상 평가 원문"}}
                    else:
                        observed = json.loads(request["messages"][-1]["content"])
                        reply = ({"tool": "cbe.verify", "args": {"message_id": observed["message_id"]}} if len(owner.calls) == 2 else
                                 {"tool": "finish", "args": {key: observed[key] for key in task["finish_report_fields"]}})
                    text = json.dumps(reply, ensure_ascii=False)
                elif len(owner.calls) == 1:
                    task = json.loads(request["messages"][1]["content"])
                    ref = next(x["ref"] for x in task["initial_observation"]["links"] if x["label"] == "나이스")
                    text = json.dumps({"tool": "portal.open", "args": {"ref": ref}})
                else:
                    observed = json.loads(request["messages"][-1]["content"])
                    text = json.dumps({"tool": "finish", "args": {k: observed[k] for k in
                                      ("system", "organization", "page_id", "authenticated")}}, ensure_ascii=False)
                self.emit({"model": "wrong-model" if owner.mode == "mismatch" else "scripted-test-fixture", "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                           "usage": {"completion_tokens": 20}})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def run_bridge(self, model="scripted-test-fixture", case_id="NP-P-01"):
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "mock/evaluate.py"),
            "--base-url", f"http://127.0.0.1:{self.server.server_port}/v1", "--model", model,
            "--out", str(self.out), "--case", case_id], capture_output=True, text=True, encoding="utf-8", timeout=15)

    def test_korean_literal_survives_http_model_reply_and_cli_verification(self):
        self.mode = "note"
        result = self.run_bridge(case_id="CBE-04")
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = json.loads((self.out / "evidence/CBE-04.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["report"]["body"], "가상 평가 원문")
        self.assertEqual(evidence["report"]["title"], "가상 알림")
        self.assertNotIn("\ufffd", json.dumps(evidence, ensure_ascii=False))
        self.assertTrue(all(evidence["checks"].values()))

    def test_public_task_to_model_and_observed_finish_to_cli(self):
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads((self.out / "results.json").read_text(encoding="utf-8"))["results"]
        self.assertEqual(next(r for r in rows if r["case_id"] == "NP-P-01")["status"], "PASS")
        self.assertEqual(len(self.calls), 2)
        schema = self.calls[0]["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["oneOf"][0]["properties"]["tool"]["const"], "portal.open")
        task = json.loads(self.calls[0]["messages"][1]["content"])
        self.assertNotIn("checks", task)
        self.assertNotIn("gold", task)
        self.assertEqual(self.calls[1]["messages"][-2]["role"], "assistant")
        self.assertFalse((self.out / "controller-error.json").exists())

    def test_two_multiline_format_errors_end_without_third_model_call(self):
        self.mode = "invalid"
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls), 2)
        rows = json.loads((self.out / "results.json").read_text(encoding="utf-8"))["results"]
        self.assertEqual(next(r for r in rows if r["case_id"] == "NP-P-01")["status"], "FAIL")

    def test_wrong_model_id_stops_before_preparing_a_run(self):
        result = self.run_bridge(model="wrong-model")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Requested model ID", result.stderr)
        self.assertFalse(self.out.exists())

    def test_provider_failure_invalidates_run_instead_of_fabricating_score(self):
        self.mode = "failure"
        result = self.run_bridge()
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads((self.out / "controller-error.json").read_text())["score_valid"])
        self.assertFalse((self.out / "summary.json").exists())

    def test_response_identity_mismatch_invalidates_the_run(self):
        self.mode = "mismatch"
        result = self.run_bridge()
        self.assertEqual(result.returncode, 2)
        self.assertIn("Response model ID differs", result.stderr)
        self.assertFalse((self.out / "summary.json").exists())

    def test_cli_deadline_during_inference_is_not_a_provider_failure(self):
        spec = importlib.util.spec_from_file_location("model_bridge", ROOT / "mock/evaluate.py")
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
        class ClosedInput(io.StringIO):
            def write(self, value):
                raise BrokenPipeError()
        initial = {"event": "task", "task": {}, "max_tool_turns": 8}
        process = SimpleNamespace(stdin=ClosedInput(), stdout=io.StringIO(json.dumps(initial) + '\n{"event":"closed"}\n'),
                                  poll=lambda: None, wait=lambda timeout: 0, terminate=lambda: None, returncode=0)
        args = SimpleNamespace(out=self.out, model="scripted-test-fixture", max_tokens=20,
                               format="text", base_url="http://127.0.0.1/v1", request_timeout=1)
        response = {"model": args.model, "choices": [{"message": {"content": '{"tool":"finish","args":{}}'}}]}
        transcript = io.StringIO()
        with patch.object(bridge.subprocess, "Popen", return_value=process), patch.object(bridge, "request", return_value=response):
            bridge.evaluate_case(args, "test-timeout", transcript)
        self.assertEqual(json.loads(transcript.getvalue())["observation"]["event"], "closed")


if __name__ == "__main__":
    unittest.main()
