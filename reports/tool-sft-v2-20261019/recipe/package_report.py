"""Publish completed synthetic evaluation evidence; weights and training data stay on D:."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
REPO=Path(r"D:\Codex\workspaces\narae_bench")
DEST=REPO/"reports/tool-sft-v2-20261019"
report=json.loads((ROOT/"outputs/comparison.json").read_text(encoding="utf-8"))
assert report["complete"] and report["audit"]["verified_new_benchmark_model_cases"]==72
DEST.mkdir(parents=True,exist_ok=False)

def copy(path,name):
    target=DEST/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)

copy(ROOT/"outputs/comparison.json","comparison.json")
copy(ROOT/"outputs/comparison.html","comparison.html")
for name in ["frozen-training-profile.json","training-kernel-amendment.json"]:copy(ROOT/name,Path("metadata")/name)
for name in ["manifest.json","verification.json"]:copy(ROOT/"data"/name,Path("data-provenance")/name)
copy(ROOT/"data/system.txt","data-provenance/system.txt")
for name in ["verification.json","controller-contract-test.json","snapshot.json","plan.json","frozen-profile.json"]:
    copy(ROOT/"evaluation"/name,Path("evaluation-metadata")/name)
copy(ROOT/"exports/verification.json","export-verification.json")
recovery_root=ROOT/"evaluation/recovery/narae2-pipe"
if recovery_root.exists():
    for name in ["plan.json","verification.json","runner.py","excluded-controller-error.json","evaluate-native.log","narae2-benchmark.log"]:
        copy(recovery_root/name,Path("recovery")/(name+".txt" if name.endswith(".log") else name))
    copy(recovery_root/"serving/narae2.json","recovery/serving.json")
    for source in ["interrupted-run","fresh-cases"]:
        for name in ["results.json","model-profile.json","model-transcript.jsonl"]:
            copy(recovery_root/source/name,Path("recovery")/source/name)
    copy(recovery_root/"interrupted-run/evidence/NP-E-WXS-READ-06.json","recovery/interrupted-read-06.json")
copy(ROOT/"exports/Start-NaraeModel.ps1","recipe/Start-NaraeModel.ps1")
for source in sorted((ROOT/"scripts").glob("*.py")):copy(source,Path("recipe")/source.name)
for record in report["models"]:
    tag=record["tag"];name=record["model"]
    for filename in ["training-report.json","best-checkpoint.json","events.jsonl"]:
        copy(ROOT/"outputs"/name/filename,Path(tag)/"training"/filename)
    for filename in ["results.json","summary.json","model-profile.json","model-transcript.jsonl"]:
        copy(ROOT/"evaluation/runs"/tag/filename,Path(tag)/"benchmark"/filename)
    evidence_root=ROOT/"evaluation/runs"/tag/"evidence"
    for path in sorted(evidence_root.rglob("*")):
        if path.is_file():copy(path,Path(tag)/"benchmark/evidence"/path.relative_to(evidence_root))
    for filename in ["results.json","transcript.jsonl"]:
        copy(ROOT/"evaluation/private"/tag/filename,Path(tag)/"heldout"/filename)
    copy(ROOT/"evaluation/serving"/(tag+".json"),Path(tag)/"serving.json")
rows="\n".join(f'| {"나래1 0.6B" if r["tag"]=="narae1" else "나래2 EXAONE 2.4B"} | {r["before_score"]:.2f} | {r["score"]:.2f} | {r["score_delta"]:+.2f} | {r["passed"]}/36 | {r["critical_incident_cases"]} |' for r in report["models"])
private="\n".join(f'- {r["model"]}: {r["private_heldout_passed"]}/24' for r in report["models"])
narae2=next(r for r in report["models"] if r["tag"]=="narae2")
body=f'''# 나래 실제 멀티턴 SFT v2

기존 v1 어댑터에서 실제 가중치를 추가 학습한 뒤 같은 고정 v2.1 벤치를 실행했습니다. [전체 조건·가중치 해시·점수](comparison.json)와 [72개 새 벤치 실행 및 48개 별도 시험 감사](evaluation-metadata/verification.json)를 함께 보관합니다.

실행 시작일은 {report["run_started_on"]}이며, 결과 작성 시각은 {report["report_created_at"]}입니다. 폴더의 날짜는 실행 시작일입니다.

| 모델 | v1 /100 | v2 /100 | 변화 | v2 통과 | 모의 중대 오류 사례 |
|---|---:|---:|---:|---:|---:|
{rows}

나래1 v2는 점수가 하락해 개선 모델로 채택하지 않습니다. 기존 v1 가중치는 보존했습니다. 나래2는 나이스 통과가 1개에서 {narae2["domains"]["NP-N"]["passed"]}개로 늘어 전체 점수가 6점 올랐습니다. 새로 통과한 과제는 `NP-N-02`·`NP-N-03`·`NP-N-04`이며, 기존에 통과했던 `NP-N-05`는 실패해 순증은 2개입니다. 문서 기안은 여전히 {narae2["domains"]["NP-E-WXS-WRITE"]["passed"]}/4개 통과입니다. 학습 손실 하락을 전반적인 업무 능력 개선으로 해석하지 않습니다.

지원 36개·환경 차단 9개입니다. 45개 분모와 원래 영역 배점을 유지하므로 최대 점수는 84.33입니다. 기존 Qwen3-4B-Instruct-2507 원본 지시 모델의 같은 조건 기록은 **20.92점·12/36 통과**이며 이번 추가 학습 작업에서 4B를 재학습·재실행하지 않았습니다.

## 실제 학습

학습 자료는 독립적으로 만든 조회·복무·기안·메신저 96개 가상 대화입니다. 각 대화의 다음 응답 2개씩 192개와 기존 v1 학습 분할의 분기·인용 16개를 사용했습니다. 이전 v1의 검증·시험 자료나 나래벤치 문제·정답을 생성기에 입력하지 않았습니다. 공개 시스템 지침·도구 인터페이스는 공유합니다. 개발자는 공개 벤치를 미리 보았으므로 블라인드 시험으로 표현하지 않습니다.

사용자·관찰·과거 대화 및 잘못된 과거 호출은 손실에서 제외하고 다음 올바른 assistant 응답과 종료 토큰만 학습했습니다. 네이티브 생성 프롬프트와 답변을 나누어 토큰화해 EXAONE 헤더의 경계 문자가 답변 손실에 섞이지 않게 했으며, 두 토크나이저에서 각 304개 레코드의 마스크를 확인했습니다. 긴 예제를 조용히 자르지 않았고 최대 길이는 0.6B 1,649, 2.4B 1,806토큰이었습니다.

각 모델은 기존 v1에서 NF4 frozen base + F32 PEFT LoRA(rank 16, alpha 32, 마지막 6층 q/v)로 2 epoch·**104회 추가 optimizer step**을 수행했습니다. 최종 사용 체크포인트는 학습한 두 epoch 중 검증 teacher loss가 낮은 쪽이며, 선택 epoch와 전체 이력은 모델별 training 폴더에 있습니다. 선택된 24개 텐서의 v1 대비 실제 변경과 GGUF F32 변환 일치를 검증했습니다. 프롬프트 프로필을 가중치 학습 모델로 부르지 않습니다.

긴 CPU 문맥의 메모리 부담을 줄이기 위해 2.4B에는 지원되는 SDPA를 사용하고 학습 전에 전체 모델의 eager/SDPA 손실 및 full/cached 손실을 대조했습니다. 0.6B의 실행 중인 eager 학습은 그대로 유지했습니다. 데이터·epoch·학습률·seed는 고정했으며 [별도 변경 기록](metadata/training-kernel-amendment.json)을 남겼습니다. 외부 벤치 점수로 학습을 재조정하거나 체크포인트를 다시 고르지 않았습니다.

## 별도 가상 시험

학습과 다른 시드·ID·연도를 사용한 24개 대화를 모델별로 실행했습니다. 템플릿은 공유하므로 새로운 업무 종류의 일반화 시험은 아닙니다. 8개에는 잘못된 과거 호출을 미리 넣어 복구를 시험했습니다. 이 수치를 나래벤치 점수와 합산하지 않았습니다.

{private}

## 비교 조건과 한계

이전 전체 점수와 비교하기 위해 [v2.1 소스](https://github.com/y5496694/narae_bench/tree/8f3283725bbcb868e640882a6652e28af069fb60)를 고정했습니다. 현재 main의 v2.2 도구 설명 개선을 이 점수에 섞지 않았습니다. 최초 과제 입력 72개가 각 v1 기록과 같고, 같은 JSON Schema·8턴·턴당 2,048토큰·temperature 0·seed 719·8K 문맥·6 CPU threads·llama.cpp b11669·Q4_K_M base를 사용했는지 확인했습니다. 실제 모델 출력이 도구 호출·관찰 기록과 일치하는지도 감사했습니다. UTF-8 `message.content`와 최종 `usage`를 사용하며 스트리밍 토큰 ID를 재디코딩하지 않습니다.

이 결과는 모의 상태와 제한된 텍스트 형식 검사이며 독립적인 의미 검수나 실제 학교 서비스 E2E가 아닙니다. 벽시계 시간에는 호스트의 다른 작업 영향이 있고 단일 seed 측정입니다. 실서비스 동작·메시지 전송은 0회입니다. 계약 테스트의 정답 절차·HTTP stub 점수는 모델 성능에 포함하지 않았습니다.

나래2는 문서 읽기 과제의 360초 제한이 끝난 뒤 Windows stdin이 `BrokenPipeError` 대신 `EINVAL`을 내 실행기가 중단됐습니다. 성공적으로 종료된 CLI에서만 이 오류를 닫힌 파이프로 처리하도록 수정했으며, 실행 중의 I/O 오류는 계속 무효 처리합니다. 완료 15개를 보존하고 중단 과제 1개·미실행 20개를 같은 가중치·프롬프트·채점·예산의 새 상태에서 복구했습니다. [복구 기록](recovery/verification.json)과 제외한 부분 기록을 보관했으며, 최종 72개 감사에서는 최초 입력 동일성과 응답 전달 일치도 다시 확인했습니다. 고정 v2.1 소스는 변경하지 않았고 복구 실행기의 전송 처리 수정만 별도 해시로 기록했습니다.

로컬 학습 데이터·모델·캐시·원본 로그는 `D:\\Codex\\training\\narae-tool-sft-v2-20261019`에 저장했습니다. 이 공개 묶음에는 감사용 코드·해시·학습 이벤트와 가상 평가 요청·응답·도구 증거를 포함합니다. 모델 가중치·학습 데이터 원본·인증정보는 포함하지 않습니다. recipe는 이 PC의 소스 사본이며 다른 PC의 경로와 의존성은 별도로 맞춰야 합니다.

브라우저 저장소에는 OpenAI 호환 응답의 다른 모델 ID를 거절하는 [수정](https://github.com/y5496694/narae_browser/commit/040728cbe510153b828074ea0cc8b204350ff8ec)도 반영했습니다. 테스트 18개를 통과했습니다. 이 변경은 모의 벤치의 실제 가중치 검증과 별도이며, 설치본의 기존 작업을 덮어쓰지는 않았습니다.
'''
(DEST/"README.md").write_text(body,encoding="utf-8")
manifest={str(p.relative_to(DEST)).replace("\\","/"):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DEST.rglob("*")) if p.is_file()}
(DEST/"manifest.json").write_text(json.dumps({"type":"completed real SFT and synthetic evaluation evidence","files":manifest},indent=2)+"\n",encoding="utf-8")
print(json.dumps({"files":len(manifest),"folder":str(DEST),"model_weights_included":False}))
