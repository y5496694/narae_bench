"""Audit paired prompts, actual token usage and unmodified model-to-tool calls."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(r"D:\Codex\workspaces\narae_bench")
frozen = json.loads((ROOT / "api-frozen-profile.json").read_text(encoding="utf-8"))
for filename, expected in frozen["source_sha256"].items():
    assert hashlib.sha256(Path(filename).read_bytes()).hexdigest() == expected, filename
spec = importlib.util.spec_from_file_location("public_bridge", REPO / "mock/evaluate.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
initial_prompts = {}
verified = []
for tag in ("narae1", "narae2", "qwen4b"):
    folder = ROOT / "api-runs" / tag
    run = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    serving = json.loads((ROOT / "serving" / (tag + ".json")).read_text(encoding="utf-8"))
    assert summary["all_cases_completed"] and summary["not_run"] == 0
    assert not (folder / "controller-error.json").exists()
    assert run["comparison_profile_sha256"] == frozen["sha256"]
    assert run["model"] == serving["identity"]["alias"]
    assert serving["executable_sha256"] == frozen["executable_sha256"]
    assert sum(r["status"] == "BLOCKED" for r in run["results"]) == 9
    active = [r for r in run["results"] if r["status"] in ("PASS", "FAIL")]
    assert len(active) == 36
    transcript = [json.loads(line) for line in (folder / "model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    for row in active:
        evidence = json.loads((folder / "evidence" / (row["case_id"] + ".json")).read_text(encoding="utf-8"))
        entries = [e for e in transcript if e["case_id"] == row["case_id"]]
        assert evidence["live_service_actions"] == 0 and 1 <= len(entries) <= 8
        trace_index = 0
        for entry in entries:
            request, response = entry["request"], entry["response"]
            assert request["model"] == response["model"] == run["model"]
            assert request["max_tokens"] == 2048 and request["temperature"] == 0 and request["seed"] == 719
            assert request["stream"] is False and request["response_format"]["type"] == "json_schema"
            assert request["messages"][0] == {"role": "system", "content": bridge.SYSTEM}
            assert 0 <= response["usage"]["completion_tokens"] <= 2048
            assert response["usage"]["prompt_tokens"] <= 8192
            if entry["turn"] == 1:
                raw = json.dumps(request["messages"][:2], ensure_ascii=False, sort_keys=True).encode()
                digest = hashlib.sha256(raw).hexdigest()
                if row["case_id"] in initial_prompts:
                    assert initial_prompts[row["case_id"]] == digest, (tag, row["case_id"])
                else:
                    initial_prompts[row["case_id"]] = digest
            if entry["observation"]["event"] == "closed":
                assert row["failure_layer"] == "TIMEOUT"
                continue
            try:
                call = bridge.parse_reply(response["choices"][0]["message"].get("content"))
            except (ValueError, TypeError):
                continue
            actual = evidence["trace"][trace_index]
            assert call == {"tool": actual["tool"], "args": actual["args"]}, (tag, row["case_id"])
            observed = {k:v for k,v in entry["observation"]["result"].items() if k != "environment"}
            assert observed == actual["result"]
            trace_index += 1
        assert trace_index == len(evidence["trace"])
        verified.append({"model": tag, "case_id": row["case_id"], "turns": len(entries), "passed": row["status"] == "PASS"})
assert len(verified) == 108 and len(initial_prompts) == 36
result = {"verified_model_cases": 108, "identical_initial_prompt_cases_across_models": 36,
          "frozen_source_files_verified": True, "native_api_token_usage_verified": True,
          "unmodified_model_calls_matched_to_cli_evidence": True, "prior_invalid_native_decoder_scores_excluded": True,
          "live_service_actions": 0, "details": verified}
(ROOT / "verification/api-comparison-verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k:v for k,v in result.items() if k != "details"}))
