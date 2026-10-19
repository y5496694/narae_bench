"""Restart only the four unfinished cases after the status-file writer failed."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
REC = ROOT / "recovery/qwen4b"
REC.mkdir(parents=True, exist_ok=True)
for folder in ["logs", "serving", "verification", "tmp"]:
    (REC / folder).mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location("native", ROOT / "runner/compare_api.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
native.ROOT = REC
for key in ["TEMP", "TMP"]:
    os.environ[key] = str(REC / "tmp")

def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(100):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 99:
                raise
            time.sleep(.05)

native.dump = dump
folder = ROOT / "api-runs/qwen4b"
original = json.loads((folder / "results.json").read_text(encoding="utf-8"))
remaining = [r["case_id"] for r in original["results"] if r["status"] == "NOT_RUN"]
assert remaining == ["CBE-08", "CBE-09", "CBE-10", "CBE-11"]
for filename in ["results.json", "model-transcript.jsonl", "controller-error.json"]:
    shutil.copyfile(folder / filename, REC / ("interrupted-" + filename))
shutil.copyfile(ROOT / "logs/api-comparison.stderr.log", REC / "orchestrator-error.log")
record = native.specification("qwen4b")
server = native.Server(record)
try:
    assert json.loads((REC / "serving/qwen4b.json").read_text(encoding="utf-8")) == json.loads((ROOT / "serving/qwen4b.json").read_text(encoding="utf-8"))
    command = [sys.executable, "-X", "utf8", str(native.REPO / "mock/evaluate.py"), "--base-url", native.BASE + "/v1",
               "--model", record["alias"], "--out", str(REC / "fresh-cases"), "--format", "schema", "--max-tokens", "2048", "--request-timeout", "600"]
    for case in remaining:
        command += ["--case", case]
    dump(ROOT / "api-status.json", {"stage": "recovering", "model": "qwen4b", "completed_before_restart": 32, "cases": remaining})
    with (REC / "logs/evaluation.log").open("wb") as log:
        result = subprocess.run(command, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0
    fresh = json.loads((REC / "fresh-cases/results.json").read_text(encoding="utf-8"))
    for index, row in enumerate(original["results"]):
        if row["case_id"] in remaining:
            new = next(r for r in fresh["results"] if r["case_id"] == row["case_id"])
            assert new["status"] in ["PASS", "FAIL"]
            original["results"][index] = new
            shutil.copyfile(REC / "fresh-cases/evidence" / (row["case_id"] + ".json"), folder / "evidence" / (row["case_id"] + ".json"))
    before = [json.loads(x) for x in (REC / "interrupted-model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    after = [json.loads(x) for x in (REC / "fresh-cases/model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    transcript = [e for e in before if e["case_id"] not in remaining] + after
    assert len({e["case_id"] for e in transcript}) == 36
    frozen = json.loads((ROOT / "api-frozen-profile.json").read_text(encoding="utf-8"))
    manifest = {"cause": "Windows status-file os.replace PermissionError closed the orchestrator; its finally block stopped the healthy inference server, resetting the controller connection.",
                "model": "qwen4b", "completed_cases_preserved": 32, "cases_restarted_from_fresh_state": remaining,
                "partial_interrupted_case_excluded": "CBE-08", "weights_and_serving_manifest_identical": True,
                "source_sha256": native.sha(__file__), "prior_invalid_partial_artifacts": str(REC),
                "no_model_or_grading_changes": True, "status_file_replace_retries_added_in_recovery_writer": True}
    original.update(model_identity=record, comparison_profile=frozen, comparison_profile_sha256=frozen["sha256"], recovery=manifest)
    dump(folder / "results.json", original)
    (folder / "model-transcript.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in transcript), encoding="utf-8")
    subprocess.run([sys.executable, "-X", "utf8", str(native.REPO / "bench.py"), "grade", str(folder / "results.json"), "--out", str(folder / "summary.json")], check=True)
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    assert summary["all_cases_completed"] and summary["not_run"] == 0
    summary.update(model_identity=record, comparison_profile=frozen, comparison_profile_sha256=frozen["sha256"], recovery=manifest)
    dump(folder / "summary.json", summary)
    shutil.move(str(folder / "controller-error.json"), str(REC / "excluded-controller-error.json"))
    dump(ROOT / "verification/qwen-recovery.json", manifest)
    dump(ROOT / "api-status.json", {"stage": "complete", "models": frozen["models"], "qwen_recovered_cases": remaining})
    print(json.dumps({"score": summary["strict_e2e_score"], "recovery": manifest}), flush=True)
finally:
    server.close()
