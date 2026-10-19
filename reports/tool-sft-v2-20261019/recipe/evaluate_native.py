"""Verify learned v2 weights and evaluate private tasks plus the frozen public v2.1 benchmark."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation"
BENCH = OUT / "benchmark"
OLD = Path(r"D:\Codex\benchmarks\narae-compare-v21-20261019")
sys.path.insert(0, str(ROOT / "scripts"))
from tool_corpus import World, dumps


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_suffix(path.suffix + ".tmp")
    stage.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    for attempt in range(100):
        try:
            stage.replace(path)
            return
        except PermissionError:
            if attempt == 99: raise
            time.sleep(.05)


spec = importlib.util.spec_from_file_location("native", OLD / "runner/compare_api.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
native.ROOT = OUT
native.REPO = BENCH
native.dump = dump
for name in ["logs", "serving", "runs", "private"]:
    (OUT / name).mkdir(exist_ok=True)
for key in ["TEMP", "TMP"]:
    os.environ[key] = str(ROOT / "tmp")
bridge_spec = importlib.util.spec_from_file_location("bridge", BENCH / "mock/evaluate.py")
bridge = importlib.util.module_from_spec(bridge_spec)
bridge_spec.loader.exec_module(bridge)


def identity(tag):
    name = "Narae-0.6B-Tool-LoRA-v2" if tag == "narae1" else "EXAONE-Narae-2.4B-Tool-LoRA-v2"
    training = load(ROOT / "outputs" / name / "training-report.json")
    assert training["actual_weight_training"] and training["optimizer_steps"] == 104
    assert training["adapter_sha256_before"] != training["adapter_sha256_after"]
    adapter = next(a for a in load(ROOT / "exports/verification.json")["verification"] if a["model"] == name)
    assert adapter["all_f32_tensors_bitwise_equal"] and adapter["tensors"] == 24
    assert sha(ROOT / "outputs" / name / "adapter/adapter_model.safetensors") == adapter["source_sha256"] == training["adapter_file_sha256"]
    assert sha(adapter["file"]) == adapter["export_sha256"]
    previous = load(OLD / "serving" / (tag + ".json"))["identity"]
    return {"tag": tag, "alias": name, "file": previous["file"], "sha256": previous["sha256"],
            "source": previous["source"], "narae_weight_training": True, "adapter": adapter,
            "optimizer_steps": training["optimizer_steps"], "starting_adapter_sha256": training["initial_adapter_file_sha256"]}


def private_tasks(record):
    target = OUT / "private" / record["tag"]
    target.mkdir()
    rows = [json.loads(x) for x in (ROOT / "data/trajectories/test.jsonl").read_text(encoding="utf-8").splitlines()]
    results = []
    with (target / "transcript.jsonl").open("x", encoding="utf-8") as log:
        for row in rows:
            w = World(row["scenario"])
            messages = [{"role": "system", "content": bridge.SYSTEM}, {"role": "user", "content": dumps(row["scenario"]["task"])}]
            if row["scenario"]["bad_prefix"]:
                tool, args = row["scenario"]["bad_prefix"]
                observation = w.call(tool, args)
                messages += [{"role": "assistant", "content": dumps({"tool": tool, "args": args})},
                             {"role": "user", "content": dumps({"event": "observation", "result": {"environment": "mock", **observation}})}]
            errors = 0
            for turn in range(8):
                payload = {"model": record["alias"], "messages": messages, "temperature": 0, "max_tokens": 2048,
                           "seed": 719, "stream": False, "response_format": {"type": "json_schema", "json_schema": {
                               "name": "narae_private_action", "schema": bridge.public_schema(row["scenario"]["task"])}}}
                response = bridge.request(native.BASE+"/v1", "/chat/completions", payload, 600)
                assert response["model"] == record["alias"] and response["usage"]["completion_tokens"] <= 2048
                text = response["choices"][0]["message"].get("content")
                try:
                    call = bridge.parse_reply(text)
                    observation = w.call(call["tool"], call["args"])
                except (ValueError, TypeError):
                    errors += 1
                    call = {}
                    observation = {"ok": False, "error": "INVALID_TOOL_JSON"}
                log.write(dumps({"case_id": row["id"], "turn": turn+1, "request": payload, "response": response, "observation": observation})+"\n")
                log.flush()
                messages += [{"role": "assistant", "content": text or ""}, {"role": "user", "content": dumps({"event": "observation", "result": {"environment": "mock", **observation}})}]
                if call.get("tool") == "finish" or errors >= 2: break
            results.append({"id": row["id"], "kind": row["kind"], "passed": w.passed(), "turns": turn+1, "report": w.report, "tool_errors": w.failures})
            dump(target / "results.json", {"complete": len(results) == 24, "passed": sum(r["passed"] for r in results), "planned": 24, "results": results,
                 "scope": "Independent synthetic templates with held-out values, not live E2E or a novel-workflow test; 8 cases include prefilled erroneous context"})
            dump(OUT / "status.json", {"stage": "private-heldout", "model": record["tag"], "completed": len(results), "passed": sum(r["passed"] for r in results)})


def main():
    training_profile = load(ROOT / "frozen-training-profile.json")
    for name, digest in training_profile["source_sha256"].items():
        assert sha(ROOT / name) == digest, name
    snapshot = load(OUT / "snapshot.json")
    for name, digest in snapshot["files_sha256"].items(): assert sha(BENCH / name) == digest
    profile = {"benchmark_profile": "high-level-mock-cli-v2.1", "max_tool_turns": 8, "max_tokens": 2048,
               "temperature": 0, "seed": 719, "context": 8192, "threads": 6, "enable_thinking": False,
               "format": "json_schema", "benchmark_files_sha256": snapshot["files_sha256"], "executable_sha256": sha(native.EXE),
               "runner_sha256": sha(__file__), "prior_baseline_root": str(OLD), "live_service_actions": 0}
    assert profile["executable_sha256"] == load(OLD / "api-frozen-profile.json")["executable_sha256"]
    dump(OUT / "frozen-profile.json", profile)
    for tag in ["narae1", "narae2"]:
        record = identity(tag)
        server = native.Server(record)
        try:
            private_tasks(record)
            folder = OUT / "runs" / tag
            command = [sys.executable, "-X", "utf8", str(BENCH / "mock/evaluate.py"), "--base-url", native.BASE+"/v1",
                       "--model", record["alias"], "--out", str(folder), "--format", "schema", "--max-tokens", "2048", "--request-timeout", "600"]
            with (OUT / "logs" / (tag+"-benchmark.log")).open("wb") as log:
                worker = subprocess.Popen(command, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
                while worker.poll() is None:
                    status = {"stage": "benchmark", "model": tag}
                    # Observe the append-only controller log. Opening the v2.1
                    # results file during os.replace can block it on Windows.
                    try:
                        progress = (OUT/"logs"/(tag+"-benchmark.log")).read_text(encoding="utf-8")
                        status["completed"] = progress.count('"case_completed":')
                    except OSError: pass
                    dump(OUT / "status.json", status)
                    time.sleep(2)
                assert worker.returncode == 0, str(folder)
            for filename in ["results.json", "summary.json"]:
                value = load(folder/filename)
                value.update(model_identity=record, v2_comparison_profile=profile)
                dump(folder/filename, value)
            summary = load(folder/"summary.json")
            assert summary["all_cases_completed"] and summary["not_run"] == 0
            print(dumps({"model": tag, "strict_score": summary["strict_e2e_score"], "private_passed": load(OUT/"private"/tag/"results.json")["passed"]}), flush=True)
        finally:
            server.close()
    dump(OUT / "status.json", {"stage": "complete"})


if __name__ == "__main__":
    main()
