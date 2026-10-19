"""Aggregate the corrected fresh API runs. Prior decoder-corrupted runs are excluded."""
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)
labels = {"narae1": "나래1 · Qwen3 0.6B SFT v1", "narae2": "나래2 · EXAONE 3.5 2.4B SFT v1",
          "qwen4b": "Qwen3-4B-Instruct-2507 · 원본 지시 모델"}
records = []
for tag in labels:
    folder = ROOT / "api-runs" / tag
    if not (folder / "results.json").exists():
        continue
    results = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    counts = Counter(r["status"] for r in results["results"])
    summary_path = folder / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
    completed = counts["NOT_RUN"] == 0 and summary is not None and not (folder / "controller-error.json").exists()
    serving = json.loads((ROOT / "serving" / (tag + ".json")).read_text(encoding="utf-8"))
    tokens, inputs, replacements = 0, 0, 0
    if (folder / "model-transcript.jsonl").exists():
        raw = (folder / "model-transcript.jsonl").read_text(encoding="utf-8")
        lines = raw.splitlines()
        if raw and not raw.endswith("\n"):
            lines = lines[:-1]
        for line in lines:
            entry = json.loads(line)
            usage = entry["response"].get("usage", {})
            tokens += usage.get("completion_tokens", 0)
            inputs += usage.get("prompt_tokens", 0)
            replacements += "\ufffd" in (entry["response"]["choices"][0]["message"].get("content") or "")
    incident_kinds = Counter(i for row in results["results"] for i in row["incidents"])
    times = [r["wall_seconds"] for r in results["results"] if r["status"] in ("PASS", "FAIL")]
    trace_audit = Counter()
    for path in sorted((folder / "evidence").glob("*.json")):
        evidence = json.loads(path.read_text(encoding="utf-8"))
        trace = evidence["trace"]
        error_count = sum(t["result"].get("ok") is False for t in trace)
        trace_audit["tool_error_responses"] += error_count
        trace_audit["cases_with_tool_errors"] += bool(error_count)
        trace_audit["cases_with_format_errors"] += bool(evidence["format_errors"])
        trace_audit["cases_using_all_eight_turns"] += len(trace) == 8
        trace_audit["cases_repeating_same_failed_call"] += any(
            trace[i]["tool"] == trace[i-1]["tool"] and trace[i]["args"] == trace[i-1]["args"]
            and trace[i-1]["result"].get("ok") is False for i in range(1, len(trace)))
    records.append({"tag": tag, "label": labels[tag], "model_id": results["model"], "completed": completed,
                    "score": summary["strict_e2e_score"] if completed else None,
                    "weighted_partial_score": round(sum(d["weight"] * d["partial_percent"] / 100 for d in summary["domains"].values()), 2) if completed else None,
                    "executed": counts["PASS"] + counts["FAIL"], "passed": counts["PASS"], "failed": counts["FAIL"],
                    "blocked": counts["BLOCKED"], "not_run": counts["NOT_RUN"],
                    "critical_incident_cases": sum(bool(r["incidents"]) for r in results["results"]),
                    "incident_kinds": dict(incident_kinds), "domains": summary["domains"] if completed else None,
                    "tool_trace_audit": dict(trace_audit),
                    "execution_recovery": results.get("recovery"),
                    "actual_narae_weight_training": serving["identity"]["narae_weight_training"],
                    "median_case_wall_seconds": round(statistics.median(times), 3) if times else None,
                    "native_api_completion_tokens": tokens, "native_api_prompt_tokens": inputs,
                    "replacement_character_response_count": replacements, "serving": serving,
                    "results_file": str(folder / "results.json"),
                    "evidence_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in sorted((folder / "evidence").glob("*.json"))}})
ready = len(records) == 3 and all(r["completed"] for r in records)
report = {"type": "Fresh local model inference through the public API-to-CLI runner, corrected UTF-8 transport",
          "date": "2026-10-19", "benchmark_profile": "high-level-mock-cli-v2.1", "complete": ready,
          "maximum_mock_score": 84.33, "supported_cases_per_model": 36, "blocked_cases_per_model": 9,
          "live_service_actions": 0, "models": records,
          "comparison_profile": json.loads((ROOT / "api-frozen-profile.json").read_text(encoding="utf-8")),
          "training_scope_audit": json.loads((ROOT / "verification/training-scope-audit.json").read_text(encoding="utf-8")),
          "limitations": "High-level mock state and limited text checks, not real school-service E2E or independent semantic review. Existing Narae v1 weights are unchanged. Qwen 4B has no Narae fine-tuning. Prior native streamed-ID decoder runs are invalid and excluded.",
          "corrections": ["Use UTF-8 API message.content, not incomplete streamed token-ID arrays, preserving Korean byte fragments.",
                          "Use native API final usage counters for the 2048-token generation budget.",
                          "Accept actually complete one-page document queries without a redundant all_pages request flag; preserve filter and has_more checks."]}
if ready:
    best = max(records, key=lambda r: (r["score"], -r["critical_incident_cases"]))
    report["highest_score_model_tag"] = best["tag"]
    report["highest_structured_score_model"] = {"narae1": "0.6b", "narae2": "2.4b", "qwen4b": "qwen3-4b-instruct-2507"}[best["tag"]]
(OUT / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
rows = []
for r in records:
    score = f'{r["score"]:.2f}' if r["completed"] else "진행 중"
    partial = f'{r["weighted_partial_score"]:.2f}' if r["completed"] else "—"
    rows.append(f'<tr><td>{html.escape(r["label"])}</td><td>{score}</td><td>{partial}</td>'
                f'<td>{r["passed"]}/{r["executed"]}</td><td>{r["critical_incident_cases"]}</td></tr>')
page = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>나래 모델 최종 재평가</title>
<style>body{{font:16px/1.7 system-ui;max-width:1100px;margin:48px auto;padding:0 24px;color:#17283c}}table{{border-collapse:collapse;width:100%}}th,td{{padding:14px;border-bottom:1px solid #d7dfe9;text-align:left}}th{{background:#edf3fa}}.note{{padding:18px;background:#f0f5fa;border-radius:10px}}a{{color:#1858bb}}</style>
<h1>나래1 · 나래2 · Qwen 4B</h1><p>올바른 한글 전송 경로와 채점 v2.1로 새 상태에서 재실행 · {"완료" if ready else "진행 중"}</p>
<table><tr><th>모델</th><th>엄격 점수 /100</th><th>부분 점수 /100</th><th>통과/실행</th><th>중대 오류 사례</th></tr>{"".join(rows)}</table>
<p class="note">모델별 지원 36개·환경 차단 9개. 45개 분모와 영역 배점을 유지해 상한은 84.33점입니다. 모든 모델에 8턴·2,048토큰·temperature 0·seed 719·8K 문맥·JSON Schema를 동일 적용했습니다. 원래 가중치는 변경하지 않았고, Qwen 4B는 나래 추가학습 전 모델입니다.</p>
<p>이전 네이티브 실행기의 스트리밍 토큰 ID 디코딩은 한글 바이트 일부를 잃었습니다. 그 잠정 점수는 제외했습니다. 이번 기록은 서버의 message.content와 최종 토큰 사용량을 사용한 새 추론입니다. 실제 학교 서비스·CBE 전송은 0회입니다.</p>
<p>점수는 모의 도구 상태와 제한된 문자 형식 검사입니다. 실제 로그인·권한·렌더링·전송이나 문서 의미의 완전성을 보장하지 않습니다. 중대 오류는 모의 오수신자 선택·허위 성공 보고 등의 태그이며 실서비스 사고가 아닙니다.</p>
<p><a href="comparison.json">전체 조건·모델 해시·도구 증거 해시 JSON</a></p></html>'''
(OUT / "comparison.html").write_text(page, encoding="utf-8")
print(json.dumps({"complete": ready, "models": [{k:r[k] for k in ("tag", "score", "weighted_partial_score", "executed", "passed")} for r in records]}))
