"""Summarize completed, independently audited v2 weights and frozen inference runs."""
import hashlib
import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OLD=Path(r"D:\Codex\benchmarks\narae-compare-v21-20261019")

def load(path): return json.loads(path.read_text(encoding="utf-8-sig"))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

audit=load(ROOT/"evaluation/verification.json")
assert audit["verified_new_benchmark_model_cases"]==72
before=load(OLD/"outputs/comparison.json")
assert before["complete"]
records=[]
for tag in ["narae1","narae2"]:
    folder=ROOT/"evaluation/runs"/tag
    result,summary=load(folder/"results.json"),load(folder/"summary.json")
    assert summary["all_cases_completed"] and summary["not_run"]==0
    previous=next(m for m in before["models"] if m["tag"]==tag)
    prior_results=load(OLD/"api-runs"/tag/"results.json")
    prior_passes={x["case_id"] for x in prior_results["results"] if x["status"]=="PASS"}
    new_passes={x["case_id"] for x in result["results"] if x["status"]=="PASS"}
    serving=load(ROOT/"evaluation/serving"/(tag+".json"))
    training=load(ROOT/"outputs"/serving["identity"]["alias"]/"training-report.json")
    selected=load(ROOT/"outputs"/serving["identity"]["alias"]/"best-checkpoint.json")
    assert training["optimizer_steps"]==104 and all(v>0 for v in training["adapter_parameter_l2_changes"].values())
    private=load(ROOT/"evaluation/private"/tag/"results.json")
    transcript=[json.loads(x) for x in (folder/"model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    private_transcript=[json.loads(x) for x in (ROOT/"evaluation/private"/tag/"transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    r={"tag":tag,"model":result["model"],"before_score":previous["score"],"score":summary["strict_e2e_score"],
       "score_delta":round(summary["strict_e2e_score"]-previous["score"],2),"before_passed":previous["passed"],
       "passed":sum(x["status"]=="PASS" for x in result["results"]),"executed":36,"blocked":9,
       "gained_pass_cases":sorted(new_passes-prior_passes),"lost_pass_cases":sorted(prior_passes-new_passes),
       "weighted_partial_score":round(sum(d["weight"]*d["partial_percent"]/100 for d in summary["domains"].values()),2),
       "critical_incident_cases":summary["critical_incident_cases"],"domains":summary["domains"],
       "private_heldout_passed":private["passed"],"private_heldout_total":24,
       "benchmark_response_count":len(transcript),
       "benchmark_length_limited_response_count":sum(e["response"]["choices"][0]["finish_reason"]=="length" for e in transcript),
       "private_length_limited_response_count":sum(e["response"]["choices"][0]["finish_reason"]=="length" for e in private_transcript),
       "replacement_character_response_count":sum("\ufffd" in (e["response"]["choices"][0]["message"].get("content") or "") for e in transcript),
       "training":training,"selected_checkpoint":selected,"serving":serving,"recovery":result.get("recovery"),
       "evidence_sha256":{p.relative_to(folder/"evidence").as_posix():sha(p) for p in sorted((folder/"evidence").rglob("*")) if p.is_file()}}
    records.append(r)
alternative=next(m for m in before["models"] if m["tag"]=="qwen4b")
scores=[(r["score"],-r["critical_incident_cases"],r["tag"]) for r in records]
scores.append((alternative["score"],-alternative["critical_incident_cases"],"qwen4b"))
report={"complete":True,"type":"Actual v1-to-v2 continued multi-turn SFT and unchanged frozen mock benchmark",
        "date":"2026-10-19","run_started_on":"2026-10-19",
        "report_created_at":datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
        "benchmark_profile":"high-level-mock-cli-v2.1","maximum_mock_score":84.33,
        "models":records,"upstream_4b_prior_comparison":{"model":alternative["model_id"],"score":alternative["score"],"passed":alternative["passed"],
                  "critical_incident_cases":alternative["critical_incident_cases"],"rerun_in_this_v2_training_job":False},
        "highest_score_model":max(scores)[2],"training_profile":load(ROOT/"frozen-training-profile.json"),
        "training_kernel_amendment":load(ROOT/"training-kernel-amendment.json"),
        "dataset":load(ROOT/"data/manifest.json"),"evaluation_profile":load(ROOT/"evaluation/frozen-profile.json"),"audit":audit,
        "live_service_actions":0,"limitations":["Known public benchmark; developer prior exposure, not a blind general-capability test",
             "Independent synthetic training generator shares public interfaces only; same templates with held-out values in private test",
             "Validation teacher loss selects checkpoint before external benchmark; no benchmark-score-driven retuning",
             "Mock state/text checks, no independent semantic review or live school service execution",
             "Q4_K_M inference base and F32 learned LoRA; v1-to-v2 weight changes are real, not prompt profiles",
             "One fixed seed and host activity affects case timeouts; not a controlled throughput study"]}
(ROOT/"outputs/comparison.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
rows=[]
for r in records:
    name="나래1 · 0.6B" if r["tag"]=="narae1" else "나래2 · EXAONE 2.4B"
    rows.append(f'<tr><td>{name}</td><td>{r["before_score"]:.2f}</td><td>{r["score"]:.2f}</td><td>{r["score_delta"]:+.2f}</td><td>{r["passed"]}/36</td><td>{r["critical_incident_cases"]}</td></tr>')
page=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>나래 실제 멀티턴 SFT v2 비교</title>
<style>body{{font:16px/1.7 system-ui;max-width:1100px;margin:48px auto;padding:0 24px;color:#1a2c42}}table{{border-collapse:collapse;width:100%}}th,td{{padding:14px;text-align:left;border-bottom:1px solid #d9e0e8}}th{{background:#edf4fa}}.note{{background:#f0f5fa;padding:18px;border-radius:12px}}</style>
<h1>나래1·나래2 실제 추가 학습 결과</h1><p>고정 v2.1 벤치 · v1 → 다중 턴 SFT v2 · 각 36개 지원 과제 실행 완료</p>
<p>실행 시작: {report["run_started_on"]} · 결과 작성: {html.escape(report["report_created_at"])}</p>
<table><tr><th>모델</th><th>v1 /100</th><th>v2 /100</th><th>변화</th><th>v2 통과</th><th>모의 중대 오류</th></tr>{"".join(rows)}</table>
<p>대안 Qwen3-4B-Instruct-2507의 기존 같은 조건 기록: {alternative["score"]:.2f}점·{alternative["passed"]}/36 통과. 이번 추가 학습 작업에서 4B를 재학습하거나 재실행하지 않았습니다.</p>
<p class="note">학습 96개 대화에서 다음 응답 192개를 뽑고 기존 학습 16개를 함께 사용했습니다. 기존 v1 어댑터에서 2 epoch·104 optimizer step씩 실제 추가 학습했습니다. 사용자·도구 관찰·잘못된 과거 호출은 손실에서 제외했습니다. 검증 손실로 체크포인트를 선택한 뒤 외부 벤치 점수를 측정했습니다.</p>
<p>이전과 같은 과제·최초 입력·도구 설명·채점·추론 실행 파일·양자화 베이스·8턴·2,048토큰·temperature 0·seed 719를 확인했습니다. 지원 36개·환경 차단 9개, 45개 분모를 유지해 상한은 84.33점입니다. 새 72개 실행과 별도 가상 시험 48개를 감사했습니다.</p>
<p>벤치는 공개 자료이며 개발자는 내용을 미리 알았습니다. 모의 상태와 제한된 텍스트 검사 결과로, 실제 학교 서비스나 문서 의미 전체를 보장하지 않습니다. 모든 동작은 로컬 가상 실행이며 실서비스 동작은 0회입니다.</p>
<p><a href="comparison.json">학습·가중치·조건·전체 점수 JSON</a></p></html>'''
(ROOT/"outputs/comparison.html").write_text(page,encoding="utf-8")
print(json.dumps({"models":[{k:r[k] for k in ["tag","before_score","score","score_delta","passed","private_heldout_passed"]} for r in records],"highest_score_model":report["highest_score_model"]}))
