"""Paired three-case diagnostic of explicit nested-argument documentation."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
BASELINE = Path(r"D:\Codex\benchmarks\narae-compare-v21-20261019")
REPO = Path(r"D:\Codex\workspaces\narae_bench")
CASES = ["NP-P-01", "NP-E-WXS-WRITE-01", "NP-N-03"]
for name in ["logs", "serving", "verification", "tmp", "runs"]:
    (ROOT / name).mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location("verified_serving", BASELINE / "runner/compare_api.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
native.ROOT = ROOT
bridge_spec = importlib.util.spec_from_file_location("public_runner", REPO / "mock/evaluate.py")
bridge = importlib.util.module_from_spec(bridge_spec)
bridge_spec.loader.exec_module(bridge)
for key in ["TEMP", "TMP"]:
    os.environ[key] = str(ROOT / "tmp")
shutil.copyfile(BASELINE / "verification/bases.json", ROOT / "verification/bases.json")
assert json.loads((BASELINE / "verification/api-comparison-verification.json").read_text())["verified_model_cases"] == 108
profile = {"type": "three-case documentation diagnostic, not a full benchmark score", "cases": CASES,
           "profile": "high-level-mock-cli-v2.2", "max_tokens": 2048, "max_turns": 8, "temperature": 0, "seed": 719,
           "baseline": str(BASELINE), "source_sha256": {name: native.sha(REPO / name)
               for name in ["mock/evaluate.py", "mock/cli.py", "mock/mock_workflow.py"]},
           "runner_sha256": native.sha(__file__), "live_service_actions": 0}
native.dump(ROOT / "profile.json", profile)
models = []
for tag in ["narae1", "narae2", "qwen4b"]:
    native.dump(ROOT / "status.json", {"stage": "evaluating", "model": tag})
    record = native.specification(tag)
    assert record == json.loads((BASELINE / "serving" / (tag + ".json")).read_text(encoding="utf-8"))["identity"]
    server = native.Server(record)
    try:
        manifest = json.loads((ROOT / "serving" / (tag + ".json")).read_text(encoding="utf-8"))
        previous_manifest = json.loads((BASELINE / "serving" / (tag + ".json")).read_text(encoding="utf-8"))
        assert manifest == previous_manifest
        out = ROOT / "runs" / tag
        command = [sys.executable, "-X", "utf8", str(REPO / "mock/evaluate.py"), "--base-url", native.BASE + "/v1",
                   "--model", record["alias"], "--out", str(out), "--format", "schema", "--max-tokens", "2048",
                   "--request-timeout", "600"]
        for case in CASES:
            command += ["--case", case]
        with (ROOT / "logs" / (tag + "-evaluation.log")).open("wb") as log:
            result = subprocess.run(command, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        assert result.returncode == 0, tag
        run = json.loads((out / "results.json").read_text(encoding="utf-8"))
        assert run["profile"] == profile["profile"]
        previous = json.loads((BASELINE / "api-runs" / tag / "results.json").read_text(encoding="utf-8"))
        entries = [json.loads(x) for x in (out / "model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
        before = [json.loads(x) for x in (BASELINE / "api-runs" / tag / "model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
        paired = []
        for case in CASES:
            first = next(e for e in entries if e["case_id"] == case and e["turn"] == 1)
            old = next(e for e in before if e["case_id"] == case and e["turn"] == 1)
            assert first["request"]["messages"][0] == old["request"]["messages"][0]
            task = json.loads(first["request"]["messages"][1]["content"])
            oldtask = json.loads(old["request"]["messages"][1]["content"])
            tool = {"NP-E-WXS-WRITE-01": "wxs.apply", "NP-N-03": "neis.prepare"}.get(case)
            if tool:
                assert task["available_tools"][tool] != oldtask["available_tools"][tool]
                task["available_tools"][tool] = oldtask["available_tools"][tool]
            assert task == oldtask, (tag, case)
            newrow = next(r for r in run["results"] if r["case_id"] == case)
            oldrow = next(r for r in previous["results"] if r["case_id"] == case)
            assert newrow["status"] in ["PASS", "FAIL"]
            evidence = json.loads((out / "evidence" / (case + ".json")).read_text(encoding="utf-8"))
            index = 0
            for entry in [e for e in entries if e["case_id"] == case]:
                if entry["observation"]["event"] == "closed":
                    assert newrow["failure_layer"] == "TIMEOUT"
                    continue
                try:
                    call = bridge.parse_reply(entry["response"]["choices"][0]["message"].get("content"))
                except (ValueError, TypeError):
                    continue
                actual = evidence["trace"][index]
                assert call == {"tool": actual["tool"], "args": actual["args"]}
                assert {k:v for k,v in entry["observation"]["result"].items() if k != "environment"} == actual["result"]
                index += 1
            assert index == len(evidence["trace"]) and evidence["live_service_actions"] == 0
            paired.append({"case_id": case, "before": oldrow["status"], "after": newrow["status"],
                           "checks_before": oldrow["checks"], "checks_after": newrow["checks"], "incidents_after": newrow["incidents"]})
        for entry in entries:
            assert entry["request"]["max_tokens"] == 2048 and entry["request"]["temperature"] == 0
            assert entry["request"]["seed"] == 719 and entry["request"]["response_format"]["type"] == "json_schema"
            assert entry["request"]["model"] == entry["response"]["model"] == record["alias"]
            assert entry["response"]["usage"]["completion_tokens"] <= 2048
            assert entry["response"]["usage"]["prompt_tokens"] <= 8192
        models.append({"tag": tag, "alias": record["alias"], "before_passed": sum(c["before"] == "PASS" for c in paired),
                       "after_passed": sum(c["after"] == "PASS" for c in paired), "total": 3, "cases": paired})
        native.dump(ROOT / "diagnostic.json", {"complete": len(models) == 3, "full_benchmark_score": None,
                    "is_full_benchmark": False, "profile": profile, "models": models,
                    "only_public_tool_descriptions_changed_in_paired_tasks": True})
        print(json.dumps({"tag": tag, "before": models[-1]["before_passed"], "after": models[-1]["after_passed"]}), flush=True)
    finally:
        server.close()
native.dump(ROOT / "status.json", {"stage": "complete"})
