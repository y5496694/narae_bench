"""Build a new immutable report bundle from the local D: audit artifacts."""
import hashlib
import json
from pathlib import Path
import shutil

WORK=Path(__file__).resolve().parent
REPO=Path('D:/Codex/workspaces/narae_bench')
OUT=REPO/'reports/failure-audit-20261020'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def dump(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def copy(source,target):target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)

OUT.mkdir(parents=True,exist_ok=True)
for name in ['before.json','after.json','comparison.json','diagnostic-plan.json','diagnostic-serving.json','diagnostic-verification.json','tests-before.txt','tests-after.txt']:
    copy(WORK/name,OUT/name)
for p in (WORK/'source-before').glob('*.py'):copy(p,OUT/'source-before'/p.name)
for name in ['mock/mock_workflow.py','mock/cli.py','mock/evaluate.py','mock/contracts.py','tests/verify_failure_contracts.py']:
    copy(REPO/name,OUT/'source-after'/name)
for name in ['audit.py','analyze.py','probe.py','build_report.py','verify_publication.py']:
    copy(WORK/name,OUT/'recipe'/name)
for name in ['verify_mock.py','verify_mock_v2.py','verify_model_runner.py','verify_coverage.py','verify_windows_storage.py','verify_write_contracts.py']:
    copy(WORK/(name+'.log'),OUT/'tests'/(name+'.txt'))
for name in ['results.json','summary.json','model-profile.json','model-transcript.jsonl']:
    copy(WORK/'diagnostic'/name,OUT/'diagnostic'/name)
for p in (WORK/'diagnostic/evidence').glob('*.json'):copy(p,OUT/'diagnostic/evidence'/p.name)
a=read(WORK/'comparison.json');diag=read(WORK/'diagnostic-verification.json')
assert diag['passed']==3 and len(diag['rows'])==6
for relative,digest in diag['source_sha256'].items():assert sha(REPO/relative)==digest
verification={'type':'Code and evidence verification, not a new full-model score',
    'comparable_full_runs':6,'historical_executed_cases_audited':216,'historical_passes':43,
    'original_profile':'high-level-mock-cli-v2.1','new_profile':'high-level-mock-cli-v2.4',
    'source_before_commit':'d7499affcd64ae8359ee498cce2245e3081d45d0',
    'exact_call_replay_before_passes':43,'exact_call_replay_after_passes':45,
    'replay_changed_checksets':4,'replay_cases_with_changed_observations':36,
    'new_failure_regression_methods':9,'existing_positive_mock_cases':36,'existing_negative_mock_controls':4,
    'mock_v2_regressions':5,'bridge_regressions':9,'coverage_regressions':4,'windows_storage_integration':1,
    'writing_regressions':5,'diagnostic_model_cases':6,'diagnostic_model_passed':3,
    'diagnostic_transcript_calls_verified':17,'historical_result_sets_in_inventory':len(a['result_inventory']),
    'narae1_narae2_v2_private_identical_first_inputs':a['narae1_narae2_v2_private_identical_first_inputs'],
    'historical_scores_modified':False,'model_weights_or_training_data_included':False,
    'weight_training_performed':False,'live_service_actions':0}
dump(OUT/'verification.json',verification)

lines=['# 나래 벤치 전체 실패 감사 · 2026-10-20','',
'**동일 v2.1·동일 예산의 여섯 체크포인트 실행 216건을 대조했고, 173건이 실패했습니다.** 추가 채점·도구 오류를 수정한 v2.4와 실제 나래3 후속 진단을 함께 공개합니다. 기존 원문·점수는 수정하지 않았습니다. 모든 동작은 가상 서비스이며 실서비스 동작과 가중치 학습은 0회입니다.','',
'## 비교 범위','',
'같은 36개 지원 과제, 8턴·턴당 2,048토큰·temperature 0·seed 719·8K 문맥·6 CPU threads·네이티브 JSON Schema 조건의 완료 실행만 공통 실패 순위에 넣었습니다. 매번 환경 차단 9개는 실행 실패율에서 제외했습니다. 여섯 실행에는 같은 기반 모델의 학습 전후 버전이 있어 독립 표본의 실패 확률 추정으로 해석하지 않습니다.','',
'| 체크포인트 | 기존 엄격 점수 /100 | 통과 /36 | 실패 /36 |','|---|---:|---:|---:|']
for m in a['models']:lines.append(f"| {m['run']} | {m['score']:.2f} | {m['passed']} | {m['failures']} |")
lines+=['','Codex 보조 실행은 v1·정답/구현 사전 노출·다른 실행기 조건으로 81.09점, 34/36개 통과였습니다. 공정한 동급 모델 비교나 이번 216건에 합산하지 않았습니다. 당시 NP-E-06·CBE-06 실패에서 확인한 채점 문제는 이미 v2에 반영됐습니다. [원본 기록](../codex-self-20261019.json)도 보존합니다.','',
'## 실패율이 큰 영역','',
'| 영역 | 실패 / 실행 | 실패율 |','|---|---:|---:|']
for d in a['domains']:lines.append(f"| {d['domain']} | {d['failures']}/{d['trials']} | {d['failure_percent']:.2f}% |")
lines+=['','19개 과제에서 여섯 실행이 모두 실패했습니다. 순위와 216건의 실제 호출·필드 불일치는 [기계 판독 대조](comparison.json), [수정 전 재생](before.json), [수정 후 재생](after.json)에 있습니다. 입력 결과와 증거 222개 파일의 SHA-256도 기록했습니다.','',
'## 확인한 오류와 수정','',
'1. **동등한 CBE 기한·업무 표현을 오답 처리**: `2026-11-24 15:00`과 `2026. 11. 24. 15:00`, 동일 시각의 ISO 시간대를 비교합니다. `참가 명단 제출 기한 정정/변경`도 해당 업무의 제한된 동등 표현으로 인정합니다. 날짜만 보고한 경우, 잘못된 시각·옛 기한·취소/부정 표현은 계속 실패합니다. 자유 문장 전체를 자동 의미 채점하는 기능은 아닙니다.',
'2. **미열람 첨부 ID의 숨겨진 순서 요구**: `unread_ids`, `content_unknown_ids`, `read_ids`, `unreadable_ids`는 중복 없는 같은 집합이면 순서와 무관하게 처리합니다. 결재 경로 등 순서가 필요한 구조의 검사는 유지합니다.',
'3. **직접 수행한 내 조직→전체 조직 검색 이력 소실**: `my`에서 실제 0명 확인 후 `all`을 별도 호출해도 두 단계 이력과 fallback을 보존합니다. 자동 전환만 정답으로 취급하던 문제를 고쳤습니다. 검색 오류는 성공한 0명 결과로 기록하지 않습니다.',
'4. **잘못된 검색 범위·열거값·불리언을 정상 요청으로 수용**: `my_documents|registry|circulation`, `A|B|C`, 문자열 `"true"` 같은 입력은 결과를 반환하기 전에 오류로 처리합니다. CBE 검색 범위도 확인합니다.',
'5. **일부 필터를 검사하지 않아 틀린 조회도 통과 가능**: NP-E-05의 A/B/C는 등록대장 범위인지, NP-E-06은 요청 기간과 검색어가 맞는지 대조합니다. 정답 보고를 평가자가 주입한 부정 대조 절차로 기존 허점을 재현했습니다. 모델이 이렇게 통과했다는 주장이 아닙니다.',
'6. **인자·보고 의미 불명확**: 자주 오용한 `documents.query`, `cbe.search`, `wxs.read`, `wxs.apply`, `neis.prepare`의 공개 JSON 인자 Schema를 추가했습니다. 출처는 사실 문장이 아니라 관찰한 문단/표 위치라는 점, body/title은 실제 값이라는 점 등도 명시합니다. 스키마에는 정답 ID·날짜·본문이 없습니다. 서버에 요청하는 Schema에도 전달하고 실행 프로필에 새 계약 파일의 해시를 기록합니다.','',
'[새 회귀 검사](source-after/tests/verify_failure_contracts.py)는 수정 전 실패를 재현했고 9개 메서드가 수정 후 모두 통과했습니다. 잘못된 기한·부정 업무·중복 ID·검색 실패 등의 부정 대조도 포함합니다. 기존 36개 양성·4개 음성 모의 과제, CLI, 브리지·커버리지·Windows 저장·기안 회귀 검사도 통과했습니다. 이 대조 절차들은 개발자 코드 검사이며 모델 점수가 아닙니다.','',
'## 기존 호출을 재생한 결과','',
'기존 216건의 도구 인자와 최종 보고를 그대로 재생했습니다. 수정 전에는 모든 체크가 원본과 같았습니다. 수정 후에는 네 체크 집합이 바뀌었고 전체 통과는 43→45건입니다. Qwen 원본과 나래3의 CBE-07 각 1건은 관찰값이 그대로인 채 동등 표현 인정으로 통과가 됩니다. 두 모델의 CBE-08은 기한/업무 체크는 통과로 바뀌지만 읽지 못한 메시지 누락 때문에 여전히 전체 실패입니다.','',
'새 입력 검증·검색 이력 때문에 36건은 도구 응답 자체도 바뀝니다. 모델이 새 오류에 대응해 다음 출력을 만든 실험이 아니므로 재생 45/216을 새 모델 성능으로 부르지 않습니다. 원래 점수 파일은 전부 그대로입니다.','',
'## 실제 나래3 후속 진단 · 전체 점수와 별도','',
'공통 실패에서 고른 6개를 동일한 실제 나래3 가중치·어댑터 강도 1·예산으로 v2.4에서 새로 실행했습니다. 사전 [실행 계획](diagnostic-plan.json), [실제 로드 명세](diagnostic-serving.json), [원문 대화](diagnostic/model-transcript.jsonl), [검증](diagnostic-verification.json)을 남겼습니다. 17개 모델 응답과 실제 도구 인자·관찰·토큰 한도를 대조했고 네이티브 실행기도 새 Schema를 처리했습니다.','',
'| 과제 | 기존 나래3 v2.1 | 새 v2.4 진단 |','|---|---|---|']
for r in diag['rows']:lines.append(f"| {r['case_id']} | FAIL | {r['status']} |")
lines+=['','선택 과제 0/6→3/6이며 전체 36개 모델 점수를 재측정한 결과가 아닙니다. 공개 설명·입력 Schema·도구·채점이 함께 바뀌어 각각의 효과를 분리할 수도 없습니다. 결과로 어댑터를 다시 고르거나 기본 모델을 바꾸지 않았습니다. 부분 실행의 summary를 전체 벤치 점수로 해석하지 않습니다.','',
'## 남아 있는 실패와 다음 우선순위','',
f"- **본문 입력 생략**: 기존 기안 24건 모두 `wxs.apply` 호출이 없고, 새 진단도 `wxs.save → wxs.saved → finish`로 빈 본문을 저장했습니다. [이전 기안 감사](../write-bench-audit-20261020/README.md)의 결과가 유지됩니다. 저장 전에 필수값을 채우는 여러 단계 학습과 새 비공개 과제 검증이 필요합니다.",
'- **이전 날짜를 그대로 수용**: NP-N-01은 6개 중 5개가 첫 stale 응답 뒤 finish했고, 나머지는 반복하다 종료했습니다. 새 진단도 2026-10-18 결과를 19일 요청의 완료로 보고했습니다. 요청 날짜와 실제 반환 날짜의 대조·재조회·실패 보고가 우선입니다.',
'- **검색 역할·범위·필터 혼동**: Qwen 원본·나래3는 내가 기안한 문서에 접수·결재 역할도 합쳐 보고했습니다. 등록대장 새 진단 역시 내 문서 범위를 고르고 A/B/C 조건까지 섞어 실패했습니다. 조건 선택과 한정된 결과 집합 보존이 필요합니다.',
'- **출처 보고 누락과 사실 혼동**: 문서 본문/다중 창/허위 지시 과제 18건 중 6건은 사실이 맞지만 출처 위치 대신 사실 문장을 복사했습니다. 새 설명으로 실제 READ-02 진단은 위치 근거까지 통과했습니다. 나머지 기록에는 일정 누락·기한 시간 손실도 있어 전체 읽기 실패를 형식 탓으로 돌리지 않습니다.',
'- **메신저 원문·대상·첨부·완료 보고**: 동명이인 선택 뒤 fallback 오보고, 원문 임의 변경, 기존 방 ID 누락, 동명 파일 경로 손실, 확인되지 않은 전송 보고가 남습니다. 원문 그대로 보내라는 과제와 최종 상태 보고를 구분하고 서버 ID·해시를 유지하는 과제가 필요합니다.',
f"- 기존 전체 기록에서 `finish`가 없던 실행은 {a['trace_findings']['no_finish_count']}건, 명시적인 인자/ID 오류가 있었던 실행은 {a['trace_findings']['cases_with_argument_or_id_errors']}건입니다. 중복 가능한 진단 지표이며 실패 건수에 더해 합산하지 않습니다.",
'','실패는 현재 가상 벤치의 관찰 결과입니다. 실제 학교 계정·포털/CBE/나래 브라우저에서 발생한 장애로 단정할 근거가 없어 해당 실서비스 코드는 이번에 바꾸지 않았습니다. 공개 벤치 답안을 추가 학습시키기보다 수정된 계약을 고정하고 별도 업무 자료로 모델을 검증하는 것이 다음 단계입니다.','',
'## 별도 자료 전체 목록','',
'기존 결과 파일 23묶음을 확인했습니다. 중단 후 복구 기록은 최종 실행과 중복돼 합산하지 않았고, v2.2의 일부 과제·형식 진단·검증/보존 과제·새 가상 시험은 조건이 달라 공통 순위에서 분리했습니다. 아래 별도 가상 시험에서 나래1·2 v2는 같은 24개 과제이며 최초 입력이 전부 같음을 원문으로 대조했습니다. 나래3는 다른 값의 새 과제이므로 나래1·2와 동일 문제의 승패로 비교하지 않습니다.','',
'| 모델 | 검색 | 복무 | 작성 | 전송 |','|---|---:|---:|---:|---:|']
for h in a['separate_heldout_kind_breakdown']:
    cols=[f"{h['by_kind'][k]['passed']}/{h['by_kind'][k]['total']}" for k in ['query','neis','write','message']]
    lines.append('| '+h['run']+' | '+' | '.join(cols)+' |')
lines+=['','| 기존 결과 경로 | 분리한 트랙 | 행/상태 |','|---|---|---|']
for item in a['result_inventory']:
    lines.append(f"| [{item['path']}](../../{item['path']}) | {item['track']} | {item['rows']}: {item['statuses']} |")
lines+=['','## 과제별 기존 판정 전체','',
'| 과제 | 이름 | 실패 /6 | narae1-v1 | narae2-v1 | qwen4b-base | narae1-v2 | narae2-v2 | narae3 |',
'|---|---|---:|---|---|---|---|---|---|']
for r in a['ranking']:
    status=['PASS' if m['run'] in r['passed_runs'] else 'FAIL' for m in a['models']]
    lines.append('| '+r['case_id']+' | '+r['name']+f" | {r['failures']}/6 | "+' | '.join(status)+' |')
lines+=['','## 재현·보관','',
'현재 계약은 `high-level-mock-cli-v2.4`입니다. [수정 전](source-before/)·[수정 후](source-after/) 소스, [분석 레시피](recipe/), [검증 요약](verification.json), 테스트 로그와 SHA-256 manifest를 보관합니다. 재생에는 원래 저장소의 cases.json과 가상 fixture가 필요하며 `mock/cli.py prepare`로 새 D: 상태 경로를 먼저 만듭니다. 예:','',
'```powershell',
'python mock/cli.py prepare --out D:\\Codex\\benchmarks\\failure-audit-replay',
'python reports/failure-audit-20261020/recipe/audit.py --state D:\\Codex\\benchmarks\\failure-audit-replay --source reports/failure-audit-20261020/source-before/mock_workflow.py --out D:\\Codex\\benchmarks\\failure-before.json',
'python reports/failure-audit-20261020/recipe/audit.py --state D:\\Codex\\benchmarks\\failure-audit-replay --source reports/failure-audit-20261020/source-after/mock/mock_workflow.py --out D:\\Codex\\benchmarks\\failure-after.json',
'python tests/verify_failure_contracts.py','```','',
'레시피의 기본 저장소 위치는 이 PC의 `D:\\Codex\\workspaces\\narae_bench`입니다. 다른 위치에서는 스크립트의 REPO/ROOT 경로를 맞춥니다. 실제 모델 진단 레시피는 별도 D: 가중치와 네이티브 실행기 및 기존 runtime.py를 참조합니다. 가중치·학습 원본·실제 계정 정보·네이티브 서버 로그는 공개 묶음에 포함하지 않습니다.']
(OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
dump(OUT/'manifest.json',{'type':'Historical failure audit, regression controls and selected actual-model diagnostic; no weights',
    'files':{p.relative_to(OUT).as_posix():sha(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p!=OUT/'manifest.json'}})
print(json.dumps({'files':len(read(OUT/'manifest.json')['files']),'path':str(OUT)}))
