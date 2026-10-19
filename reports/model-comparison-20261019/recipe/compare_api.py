"""Verified local weights, common public API-to-mock-CLI evaluation, fresh runs."""
import atexit
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(r"D:\Codex\workspaces\narae_bench")
TRAIN = Path(r"D:\Codex\training\narae-sft-20261019")
EXE = Path(r"D:\Codex\tools\llama-b11669-win-cpu\llama-server.exe")
BASE = "http://127.0.0.1:18464"
for key in ("TEMP", "TMP"):
    (ROOT / "tmp").mkdir(exist_ok=True)
    os.environ[key] = str(ROOT / "tmp")
os.environ["PYTHONPYCACHEPREFIX"] = str(ROOT / "cache/pycache")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as response:
        return json.load(response)


def specification(tag):
    if tag == "qwen4b":
        source = json.loads(Path(r"D:\Codex\models\Qwen3-4B-Instruct-2507-Q4_K_M\verified-source.json").read_text(encoding="utf-8"))
        return {"tag": tag, "alias": "Qwen3-4B-Instruct-2507", "file": source["file"], "sha256": source["sha256"],
                "source": source, "narae_weight_training": False, "adapter": None}
    size = "0.6b" if tag == "narae1" else "2.4b"
    alias = "Narae-0.6B-LoRA-v1" if tag == "narae1" else "EXAONE-Narae-2.4B-LoRA-v1"
    bases = json.loads((ROOT / "verification/bases.json").read_text(encoding="utf-8-sig"))
    exports = json.loads((TRAIN / "exports/verification.json").read_text(encoding="utf-8"))
    adapter = next(a for a in exports["verification"] if a["model"] == alias)
    training = json.loads((TRAIN / "outputs" / alias / "training-report.json").read_text(encoding="utf-8"))
    assert training["actual_weight_training"] and adapter["all_f32_tensors_bitwise_equal"]
    assert sha(TRAIN / "outputs" / alias / "adapter/adapter_model.safetensors") == adapter["source_sha256"] == training["adapter_file_sha256"]
    assert sha(adapter["file"]) == adapter["export_sha256"]
    return {"tag": tag, "alias": alias, "file": bases[size]["path"], "sha256": bases[size]["sha256"],
            "source": json.loads((TRAIN / "models" / (size + "-source.json")).read_text(encoding="utf-8")),
            "narae_weight_training": True, "adapter": adapter, "optimizer_steps": training["optimizer_steps"]}


class Server:
    def __init__(self, record):
        assert sha(record["file"]) == record["sha256"], "Model weight hash mismatch"
        command = [str(EXE), "--model", record["file"], "--alias", record["alias"],
                   "--host", "127.0.0.1", "--port", "18464", "--threads", "6", "--threads-batch", "6",
                   "--ctx-size", "8192", "--parallel", "1", "--batch-size", "512", "--ubatch-size", "128",
                   "--cache-ram", "0", "--no-context-shift", "--no-warmup", "--no-webui", "--seed", "719",
                   "--chat-template-kwargs", '{"enable_thinking":false}']
        if record["adapter"]:
            command += ["--lora", record["adapter"]["file"]]
        self.log = (ROOT / "logs" / (record["tag"] + "-server.log")).open("ab")
        self.process = subprocess.Popen(command, stdout=self.log, stderr=self.log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        atexit.register(self.close)
        deadline = time.monotonic() + 180
        while True:
            if self.process.poll() is not None:
                raise RuntimeError("Model server exited during startup")
            try:
                if get("/health").get("status") == "ok":
                    break
            except (OSError, TimeoutError):
                pass
            if time.monotonic() > deadline:
                raise TimeoutError("Model server startup timeout")
            time.sleep(0.25)
        adapters = get("/lora-adapters")
        if record["adapter"]:
            assert len(adapters) == 1 and adapters[0]["scale"] == 1
            assert Path(adapters[0]["path"]).resolve() == Path(record["adapter"]["file"]).resolve()
        else:
            assert adapters == []
        assert record["alias"] in [m["id"] for m in get("/v1/models")["data"]]
        dump(ROOT / "serving" / (record["tag"] + ".json"),
             {"identity": record, "loaded_adapters": adapters, "command": command, "executable_sha256": sha(EXE),
              "output_protocol": "OpenAI-compatible UTF-8 JSON message.content; native final usage counters"})

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.log.close()


def main():
    paths = [Path(__file__), ROOT / "Start-NaraeModel.ps1", REPO / "mock/evaluate.py", REPO / "mock/cli.py",
             REPO / "mock/mock_workflow.py", REPO / "bench.py", REPO / "cases.json"]
    profile = {"benchmark_profile": "high-level-mock-cli-v2.1", "transport": "UTF-8 API message.content, no token-ID reconstruction",
               "native_engine": "llama.cpp b11669 CPU Q4_K_M, learned F32 LoRA for narae1/2",
               "threads": 6, "context": 8192, "parallel": 1, "temperature": 0, "seed": 719,
               "max_generated_tokens_per_turn": 2048, "max_tool_turns": 8, "response_format": "json_schema",
               "enable_thinking": False, "model_request_timeout_seconds": 600,
               "live_service_actions": 0, "models": ["narae1", "narae2", "qwen4b"],
               "source_sha256": {str(p): sha(p) for p in paths}, "executable_sha256": sha(EXE),
               "prior_invalid_run": r"D:\Codex\benchmarks\narae-compare-v2-20261019\transport-invalid.json"}
    profile["sha256"] = hashlib.sha256(json.dumps(profile, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    frozen = ROOT / "api-frozen-profile.json"
    if frozen.exists():
        assert json.loads(frozen.read_text(encoding="utf-8")) == profile, "Frozen API profile changed"
    else:
        dump(frozen, profile)
    for tag in profile["models"]:
        out = ROOT / "api-runs" / tag
        if (out / "summary.json").exists():
            summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            assert summary["all_cases_completed"] and summary["comparison_profile_sha256"] == profile["sha256"]
            continue
        record = specification(tag)
        dump(ROOT / "api-status.json", {"stage": "loading", "model": tag})
        server = Server(record)
        try:
            log = (ROOT / "logs" / (tag + "-evaluation.log")).open("wb")
            command = [sys.executable, "-X", "utf8", str(REPO / "mock/evaluate.py"), "--base-url", BASE + "/v1",
                       "--model", record["alias"], "--out", str(out), "--format", "schema", "--max-tokens", "2048",
                       "--request-timeout", "600"]
            controller = subprocess.Popen(command, stdout=log, stderr=log,
                                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            while controller.poll() is None:
                result_file = out / "results.json"
                status = {"stage": "evaluating", "model": tag, "completed": 0, "passed": 0}
                if result_file.exists():
                    run = json.loads(result_file.read_text(encoding="utf-8"))
                    status.update(completed=sum(r["status"] in ("PASS", "FAIL") for r in run["results"]),
                                  passed=sum(r["status"] == "PASS" for r in run["results"]),
                                  case=next((r["case_id"] for r in run["results"] if r["status"] == "NOT_RUN"), None))
                dump(ROOT / "api-status.json", status)
                time.sleep(1)
            log.close()
            if controller.returncode:
                raise RuntimeError("Model controller failed; inspect " + str(ROOT / "logs" / (tag + "-evaluation.log")))
            for filename in ("results.json", "summary.json"):
                data = json.loads((out / filename).read_text(encoding="utf-8"))
                data.update(model_identity=record, comparison_profile=profile, comparison_profile_sha256=profile["sha256"])
                dump(out / filename, data)
            summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            assert summary["all_cases_completed"] and summary["not_run"] == 0
            print(json.dumps({"model": tag, "score": summary["strict_e2e_score"],
                              "passed": sum(c["passed"] for c in summary["cases"]), "completed": 36}), flush=True)
        finally:
            server.close()
    dump(ROOT / "api-status.json", {"stage": "complete", "models": profile["models"]})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
