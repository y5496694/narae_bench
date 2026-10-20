"""Package the benchmark's own defects separately from model workflow failures."""
import hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent;REPO=Path(r'D:\Codex\workspaces\narae_bench')
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
before=load(ROOT/'before/audit.json');after=load(ROOT/'after-final/audit.json')
bc=[c for r in before['runs'] for c in r['cases']];ac=[c for r in after['runs'] for c in r['cases']]
assert len(bc)==len(ac)==24
assert all(x['historical_checks']==x['replayed_checks']==y['replayed_checks'] for x,y in zip(bc,ac))
assert not any(c['replayed_passed'] for c in ac) and sum(c['successful_apply_count'] for c in ac)==0
cb=load(ROOT/'before/controls.json');ca=load(ROOT/'after-final/controls.json')
assert all(c['passed'] for c in cb[:4]+ca[:4])
assert all(c['passed'] for c in cb[4:6]) and not any(c['passed'] for c in ca[4:6])
assert not cb[6]['passed'] and ca[6]['passed'] and not any(c['passed'] for c in ca[7:])
probe=load(ROOT/'interface-comparison.json')
assert all(r['status']=='FAIL' and 'wxs.apply' not in r['actions'] for r in probe['runs'])
for name,digest in before['source_sha256'].items():assert sha(ROOT/'source-before'/name)==digest
for name,digest in after['source_sha256'].items():assert sha(REPO/name)==digest
verification={'verified':True,'historical_write_model_cases_replayed':24,'unchanged_checksets':24,
    'old_model_scores_changed':False,'successful_apply_calls_in_recorded_cases':0,
    'nonrecovery_cases_without_body_input':18,'public_only_controls_per_revision':9,
    'valid_public_workflow_controls_passed_before':4,'valid_public_workflow_controls_passed_after':4,
    'wrong_attachment_controls_accepted_before':2,'wrong_attachment_controls_accepted_after':0,
    'windows_newline_recovery_accepted_before':False,'windows_newline_recovery_accepted_after':True,
    'invalid_body_and_missing_attachment_still_rejected':True,'new_writing_unit_tests_passed':5,
    'other_checked_suites':{'mock_positive_cases':36,'mock_negative_cases':4,'v2_regressions':5,
        'model_runner_regressions':9,'coverage_regressions':4,'windows_storage_regressions':1},
    'paired_actual_model_format_diagnostic_cases':2,'paired_format_first_messages_equal':True,
    'paired_schema_request_matches_previous_v22_run':True,'paired_same_actual_weights_and_strength':True,
    'no_new_full_model_benchmark':True,'weight_training_performed':False,'live_service_actions':0}
dump(ROOT/'verification.json',verification)
DEST=REPO/'reports/write-bench-audit-20261020';DEST.mkdir(exist_ok=False)
def copy(source,target):
    p=DEST/target;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,p)
for tag in ['before','after']:
    source=ROOT/('before' if tag=='before' else 'after-final')
    for name in ['audit.json','controls.json']:copy(source/name,Path(tag)/name)
for name in ['verification.json','interface-plan.json','interface-serving.json','interface-comparison.json']:
    copy(ROOT/name,name)
for name in ['audit_write.py','probe_interface.py','build_report.py']:copy(ROOT/name,'recipe/'+name)
copy(REPO/'tests/verify_write_contracts.py','recipe/verify_write_contracts.py')
for name in ['tests-before.txt','tests-after.txt']:copy(ROOT/name,name)
for name in before['source_sha256']:
    copy(ROOT/'source-before'/name,Path('source-before')/name)
    copy(REPO/name,Path('source-after')/name)
for tag in ['schema','json']:
    folder=ROOT/('interface-'+tag)
    for name in ['results.json','summary.json','model-profile.json','model-transcript.jsonl']:
        copy(folder/name,Path('interface-'+tag)/name)
    for p in (folder/'evidence').rglob('*'):
        if p.is_file():copy(p,Path('interface-'+tag)/'evidence'/p.relative_to(folder/'evidence'))
labels=['나래1 0.6B v1','나래2 2.4B v1','Qwen 4B 원본','나래1 0.6B v2','나래2 2.4B v2','나래3 Qwen 4B LoRA']
table='\n'.join(f'| {name} | 0/4 | {run["partial_percent"]:.2f}% | 0/4 |' for name,run in zip(labels,before['runs']))
body=f'''# 기안 0/4 결과와 벤치 자체 감사

사용자가 모든 모델의 기안 실패를 지적해 채점과 실행 기록을 함께 확인했습니다. **벤치 오류 두 가지를 발견해 고쳤습니다. 다만 그 두 오류만으로 기존 모델의 기안 실패를 설명할 수는 없었습니다.**

## 0/4의 의미와 실제 단계

0/4는 모든 필수 조건을 만족한 과제가 없다는 뜻입니다. 문장 작성 능력 0점이나 모든 단계 수행 불가를 뜻하지 않습니다. 아래 부분 점수에는 초기값이 이미 맞던 설정도 포함하므로 직접 작성한 비율로 해석하면 안 됩니다.

| 기존 실행 | 전체 과제 통과 | 기안 영역 부분 점수 | 성공한 본문/필드 입력 호출이 있는 과제 |
|---|---:|---:|---:|
{table}

여섯 실행의 기안 24건에서 성공한 `wxs.apply` 호출은 **0회**였습니다. 복구 과제는 시작부터 일부 본문이 있으므로 새 작성과 구분했습니다. 일반 작성 18건에서도 본문 입력 호출이 없었습니다. 일부 모델은 빈 초안을 저장·재열람한 뒤, 실제 값과 다른 제목·첨부 수를 완료 보고했습니다. [원본 호출별 분해](before/audit.json)에 기존 증거 경로와 수행 단계를 기록했습니다. 수정된 채점기에 **같은 호출을 그대로 재생**한 24건에서도 체크 판정은 모두 같았습니다. 이는 새 모델 실행이나 새로운 성능 점수가 아닙니다.

## 재현하고 수정한 벤치 오류

| 검사 | 수정 전 | v2.3 수정 후 |
|---|---|---|
| 잘못된 붙임 명칭·999부 등 잘못된 수량 | 전체 과제 통과 | 붙임 검사 실패 |
| 여러 붙임에서 번호 누락 | 붙임 검사 통과 | 붙임 검사 실패 |
| 복구 본문이 동일하고 CRLF/LF만 다름 | 복구 과제 실패 | 통과 |
| 복구 본문 사실 삭제·필수 첨부 누락 | 실패 | 계속 실패 |

기존 붙임 검사는 `붙임`과 `끝.` 표기만 확인해 명칭·수량·번호를 놓쳤습니다. 이제 공개 과제의 붙임 정보와 순서를 대조합니다. 복구 과제의 본문은 줄바꿈 표현만 동등하게 처리하며, 내용·공백·나머지 필드는 유지해 비교합니다. [수정 전](before/controls.json)과 [수정 후](after/controls.json) 반례를 보존했습니다. 회귀 테스트 5개는 수정 전 5건의 실패를 재현했고 수정 후 통과했습니다. 기존 전체 모의 계약 36개와 관련 회귀 검사도 통과했습니다.

## 공개 입력만 쓰는 양성 대조

`recipe/audit_write.py`의 `public_plan()`은 모델에 제공되는 요청·초기 상태·ID 바인딩·공개 서식 규칙만 받습니다. 평가자의 `reference_body`, 정답 보고, `World.oracle`, `target_fields`를 읽지 않습니다. 요청의 사실을 보존하는 별도 문장과 붙임을 구성하고, 실제 저장 관찰값으로 완료 보고합니다. 이 절차는 수정 전후 모두 **4/4개**를 통과했습니다. 따라서 모의 API와 공개 정보로 과제를 완료하는 경로는 있습니다.

이는 벤치 코드를 이미 본 개발자가 작성한 계약 확인 절차입니다. 블라인드 대조나 모델 점수가 아니며 실제 서비스·문서 렌더링도 검증하지 않습니다. 평가 모듈 자체는 정답을 사용해 채점하지만, 대조 절차 함수는 공개 입력만 사용합니다.

## 강제 출력 형식 진단

나래3의 실제 가중치·강도 1과 동일한 공개 작성 1개를 수정 전 v2.2에서 `schema`와 `json`으로 각각 실행했습니다. 최초 입력은 같았고 Schema 요청은 이전 설치 실행기의 요청과도 동일했습니다. 8턴·턴당2048토큰·temperature0·seed719를 유지했습니다.

두 실행 모두 `wxs.save → wxs.saved → finish`로 끝나며 본문 입력을 건너뛰었습니다. 따라서 **이 한 과제에서는** 강제 Schema만의 실패로 확인되지 않았습니다. 일반적인 출력 형식 효과까지 배제한 결과는 아닙니다. [실제 요청·응답 비교](interface-comparison.json), [Schema 대화](interface-schema/model-transcript.jsonl), [JSON 대화](interface-json/model-transcript.jsonl), [실제 모델·어댑터 로드 명세](interface-serving.json)를 보관합니다. 학습이나 강도 재선택은 하지 않았습니다.

## 해석과 보존

이 벤치는 문장 작성만 분리해 측정하지 않고 도구 선택·설정·본문·첨부·저장·재확인을 함께 요구합니다. 기존 0/4를 보고 모델이 문서를 전혀 쓸 수 없다고 단정하는 것은 과도합니다. 현재 기록이 직접 보여주는 병목은 **본문 입력 도구 호출로 이어지지 못한 업무 흐름**입니다. 본문의 사실·표현을 독립적으로 평가하는 별도 시험은 필요하며, 현재 문자열 검사는 독립 의미 검수나 실제 HWP/HWPX 문서 품질 평가를 대신하지 않습니다.

채점 변경은 **high-level-mock-cli-v2.3**으로 분리했습니다. 과거 v2.1 전체 점수와 v2.2 진단을 고쳐 쓰거나 새 프로필의 새 실행 결과로 바꾸지 않았습니다. 새 전체 모델 벤치는 이번 감사에서 실행하지 않았습니다. 가중치 추가 학습·실서비스 동작은 0회이며, 모델 가중치나 실제 계정 자료도 포함하지 않습니다.

[검증 요약](verification.json), 변경 전후 소스와 재현 코드, 전체 공개 입력·관찰 증거를 함께 제공합니다. 자료와 로그 원본은 `D:\\Codex\\benchmarks\\write-bench-audit-20261020`에 있습니다.
'''
(DEST/'README.md').write_text(body,encoding='utf-8')
dump(DEST/'manifest.json',{'type':'Writing benchmark contract audit, public-only controls and paired format diagnostics; no weights',
    'files':{p.relative_to(DEST).as_posix():sha(p) for p in sorted(DEST.rglob('*')) if p.is_file()}})
print(json.dumps({'report':str(DEST),'verified':True,'files':len(load(DEST/'manifest.json')['files'])}))
