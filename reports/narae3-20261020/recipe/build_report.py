"""Package honest completed Narae3 training and synthetic evaluation evidence."""
import html,json,shutil,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from runtime import ALIAS,load,dump,sha
audit=load(ROOT/'evaluation/verification.json');assert audit['verified']
training=load(ROOT/'outputs'/ALIAS/'training-report.json');selection=load(ROOT/'outputs/selection.json')
folder=ROOT/'evaluation/run';result=load(folder/'results.json');summary=load(folder/'summary.json')
assert summary['all_cases_completed'] and summary['not_run']==0
oldroot=Path(r'D:\Codex\benchmarks\narae-compare-v21-20261019')
oldcomparison=load(oldroot/'outputs/comparison.json');original=next(m for m in oldcomparison['models'] if m['tag']=='qwen4b')
prior=load(oldroot/'api-runs/qwen4b/results.json')
prior_passes={r['case_id'] for r in prior['results'] if r['status']=='PASS'};passes={r['case_id'] for r in result['results'] if r['status']=='PASS'}
heldout=load(ROOT/'evaluation/heldout/results.json')
heldout_by_kind={kind:{'passed':sum(r['passed'] for r in heldout['results'] if r['kind']==kind),
    'total':sum(r['kind']==kind for r in heldout['results'])} for kind in sorted({r['kind'] for r in heldout['results']})}
report={'complete':True,'run_started_on':'2026-10-20','created_at':datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),
    'type':'Actual Qwen3-4B instruction-base LoRA adaptation, not a renamed prompt profile','model':ALIAS,
    'benchmark_profile':'high-level-mock-cli-v2.1','score':summary['strict_e2e_score'],'passed':len(passes),'executed':36,'blocked':9,'maximum_mock_score':84.33,
    'delta_from_upstream':round(summary['strict_e2e_score']-original['score'],2),'critical_incident_cases':summary['critical_incident_cases'],
    'weighted_partial_score':round(sum(d['weight']*d['partial_percent']/100 for d in summary['domains'].values()),2),
    'domains':summary['domains'],'gained_pass_cases':sorted(passes-prior_passes),'lost_pass_cases':sorted(prior_passes-passes),
    'upstream_comparison':{'model':original['model_id'],'score':original['score'],'passed':original['passed'],'rerun_this_job':False,
        'source':'Historical verified same-profile v2.1 run; new validation baseline was run before training'},
    'training':training,'training_profile':load(ROOT/'frozen-training-profile.json'),'dataset':load(ROOT/'data/manifest.json'),
    'selection':selection,'selection_plan':load(ROOT/'evaluation/selection-plan.json'),'audit':audit,
    'training_recovery':load(ROOT/'recovery/amendment.json'),
    'benchmark_startup_recovery':load(ROOT/'recovery/benchmark-resume-amendment.json'),
    'heldout':{'passed':heldout['passed'],'planned':24,'by_kind':heldout_by_kind,'scope':heldout['scope']},
    'serving':load(ROOT/'evaluation/serving/narae3-evaluation.json'),'export_verification':load(ROOT/'exports/verification.json'),
    'local_runtime':load(ROOT/'outputs/local-model.json'),'launcher_check':load(ROOT/'outputs/launcher-verification.json'),
    'current_cli_diagnostic':load(ROOT/'outputs/current-cli-verification.json'),
    'current_cli_diagnostic_plan':load(ROOT/'outputs/current-cli-plan.json'),
    'live_service_actions':0,'model_weights_in_public_bundle':False,'raw_training_data_in_public_bundle':False,
    'limitations':['Public benchmark and developer prior exposure; not blind','Private split uses held-out values from shared templates, not novel workflows',
        'Only eight elementary general probes; not a broad general-capability retention guarantee','One fixed seed; other host activity can affect deadlines',
        'High-level mock state/text checks, no live school-service E2E or independent document semantics review',
        'NF4 training base and Q4_K_M native inference are distinct; exported F32 tensors and actual native outputs were checked',
        'Multiple training-recipe changes together; no causal ablation of each change']}
dump(ROOT/'outputs/comparison.json',report)
page=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>나래3 실제 추가 학습 결과</title>
<style>body{{font:16px/1.7 system-ui;max-width:1000px;margin:48px auto;padding:0 24px;color:#1c3045}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:14px;border-bottom:1px solid #d8e1ec}}th{{background:#edf4fa}}.note{{padding:18px;background:#eef4fa;border-radius:12px}}</style>
<h1>나래3 · Qwen3-4B 실제 LoRA 학습</h1><p>{html.escape(report['created_at'])} · 고정 v2.1 모의 벤치</p>
<table><tr><th>모델</th><th>점수 /100</th><th>통과 /36</th></tr><tr><td>Qwen 원본 기존 기록</td><td>{original['score']:.2f}</td><td>{original['passed']}</td></tr><tr><td>나래3 실제 추가 학습</td><td>{report['score']:.2f}</td><td>{report['passed']}</td></tr></table>
<p>원본 대비 {report['delta_from_upstream']:+.2f}점. 환경 차단 9개, 최대 84.33점입니다. 기존 전체 원본 벤치는 이번에 재실행하지 않았습니다.</p>
<p class="note">164개 대화의 올바른 assistant 응답 362개를 1 epoch·41회 갱신했습니다. 검증 과제와 기존 형식·기본 지시 수행 검사를 비교한 뒤 외부 벤치를 실행했습니다. 검증 승인 여부: {selection['validation_approved_learned_model']}. 최종 평가에 사용한 실제 LoRA 강도: {selection['evaluation_candidate']['strength']}.</p>
<p>첫 시도는 41회 갱신 후 검증 코드 오류로 저장 전에 종료됐습니다. 같은 초기값·자료·조건으로 재시도했으며, 최종 가중치에 반영된 갱신은 41회입니다. 실패한 41회와 복구 기록은 별도로 보존했습니다.</p>
<p>별도 새 가상 시험: {heldout['passed']}/24개 통과. 실제 학교 서비스 동작은 0회입니다. 학습·가중치·캐시·원본 로그는 D 드라이브에 있습니다.</p>
<p><a href="comparison.json">전체 조건·학습·선택·가중치 해시·감사 JSON</a></p></html>'''
(ROOT/'outputs/comparison.html').write_text(page,encoding='utf-8')
DEST=Path(r'D:\Codex\workspaces\narae_bench/reports/narae3-20261020');DEST.mkdir(parents=True,exist_ok=False)
def copy(source,target):
    p=DEST/target;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,p)
for name in ['comparison.json','comparison.html','local-model.json','launcher-verification.json']:
    copy(ROOT/'outputs'/name,name)
for name in ['frozen-training-profile.json']:copy(ROOT/name,'metadata/'+name)
for name in ['manifest.json','train-token-audit.json','validation-token-audit.json','test-token-audit.json','native-prefix-audit.json']:
    copy(ROOT/'data'/name,'data-provenance/'+name)
for name in ['selection-plan.json','selection-plan-v1.json','snapshot.json','verification.json','validation-budget-proof.json','controller.py']:
    copy(ROOT/'evaluation'/name,'evaluation-metadata/'+name)
copy(ROOT/'outputs/selection.json','selection.json');copy(ROOT/'exports/verification.json','export-verification.json')
for name in ['training-report.json','events.jsonl']:copy(ROOT/'outputs'/ALIAS/name,'training/'+name)
copy(ROOT/'outputs'/ALIAS/'post-update-checkpoint.json','training/post-update-checkpoint.json')
for name in ['amendment.json','cache-manifest.json','benchmark-resume-amendment.json']:copy(ROOT/'recovery'/name,'recovery/'+name)
copy(ROOT/'recovery/trainer.diff','recovery/trainer-change.txt')
for name in ['train_lora_recovery.py','run_recovery.py','resume_benchmark.py']:copy(ROOT/'recovery'/name,'recipe/'+name)
for p in sorted((ROOT/'recovery/benchmark-startup-failure').iterdir()):
    copy(p,Path('recovery/benchmark-startup-failure')/(p.name+'.txt' if p.suffix=='.log' else p.name))
for p in sorted((ROOT/'recovery/launcher-windows-path').iterdir()):
    copy(p,Path('recovery/launcher-windows-path')/('manifest-before-fix.json' if p.name=='manifest.json' else p.name))
for name in ['events.jsonl','status.json']:copy(ROOT/'recovery/attempt-1/output'/name,'recovery/attempt-1/'+name)
for name in ['train_lora.log','pipeline.stderr.log']:copy(ROOT/'recovery/attempt-1'/name,'recovery/attempt-1/'+name+'.txt')
for section in ['validation','general','heldout','serving']:
    for p in sorted((ROOT/'evaluation'/section).rglob('*')):
        if p.is_file():copy(p,Path(section)/p.relative_to(ROOT/'evaluation'/section))
for name in ['results.json','summary.json','model-profile.json','model-transcript.jsonl']:copy(folder/name,'benchmark/'+name)
current=ROOT/'evaluation/current-cli'
for name in ['results.json','summary.json','model-profile.json','model-transcript.jsonl']:copy(current/name,'current-cli/'+name)
for p in sorted((current/'evidence').rglob('*')):
    if p.is_file():copy(p,Path('current-cli/evidence')/p.relative_to(current/'evidence'))
for name in ['current-cli-plan.json','current-cli-verification.json']:copy(ROOT/'outputs'/name,'current-cli/'+name)
for name,digest in report['current_cli_diagnostic_plan']['source_sha256'].items():
    source=Path(r'D:\Codex\workspaces\narae_bench')/name;assert sha(source)==digest
    copy(source,Path('current-cli/source')/name)
for p in sorted((folder/'evidence').rglob('*')):
    if p.is_file():copy(p,Path('benchmark/evidence')/p.relative_to(folder/'evidence'))
for name in load(ROOT/'evaluation/snapshot.json')['files_sha256']:
    copy(ROOT/'evaluation/benchmark'/name,Path('benchmark-snapshot')/name)
for p in sorted((ROOT/'scripts').glob('*.py')):copy(p,Path('recipe')/p.name)
for name in ['audit.py','install_model.py','test_launcher.py','prepare_recovery.py','prepare_benchmark_resume.py','verify_publication.py','build_report.py']:copy(ROOT/'evaluation'/name,'recipe/'+name)
local=Path(report['local_runtime']['path'])
for name in ['README.md','NOTICE','LICENSE','model.json','manifest.json','Start-Narae3.ps1']:copy(local/name,'local-runtime/'+name)
readme=f'''# 나래3 · Qwen3-4B 실제 추가 학습

실행 시작: {report['run_started_on']}. 결과 작성: {report['created_at']}.
Qwen3-4B-Instruct-2507에서 실제 LoRA 가중치를 학습했습니다. 이름만 바꾼 프롬프트 프로필이 아닙니다. 기반과 Apache-2.0 라이선스를 유지했습니다.

| 모델 | 엄격 점수 /100 | 통과 /36 |
|---|---:|---:|
| Qwen3-4B-Instruct-2507 원본 기존 기록 | {original['score']:.2f} | {original['passed']} |
| 나래3 실제 LoRA 추가 학습 | {report['score']:.2f} | {report['passed']} |

차이는 **{report['delta_from_upstream']:+.2f}점**입니다. 기존 전체 원본 벤치는 이번 작업에서 재실행하지 않았습니다. 원본 모델로 새 검증 과제와 기본 지시 수행 검사는 학습 전에 실행했습니다. [전체 비교 JSON](comparison.json), [감사](evaluation-metadata/verification.json), [선택 기록](selection.json)을 보관합니다.

## 학습과 선택

독립적인 가상 조회·복무·기안·메신저 대화 96개, 기존 v1 학습 분할의 분기·인용·미확인 응답 64개, 출처를 보존한 나래3 소개 4개를 사용했습니다. 전체 164개 대화의 올바른 assistant 응답 362개를 모두 학습했습니다. 사용자·관찰·잘못된 과거 assistant 구간은 손실에서 제외했습니다. 전체 대화의 미래 토큰을 바꾸어도 앞선 캐시 상태가 변하지 않는지 검사했습니다. 두 단계 중 하나와 완료 보고만 뽑던 이전 방식과 다릅니다.

NF4 frozen base/F32 LoRA, 마지막 6개 블록의 q/k/v/o/gate/up/down, rank8·alpha16·dropout0, 학습률5e-5, 1epoch·41optimizer step, seed719입니다. 약275만개 학습 파라미터이며 전체 원본 가중치를 모두 업데이트한 학습은 아닙니다. 84개 텐서의 초기값 대비 실제 변경과 F32 GGUF 변환 일치를 검증했습니다. 토큰 마스크·native HF프롬프트/토큰 일치·full/cache 및 SDPA/eager 손실·미래 토큰 비간섭 검사를 기록했습니다.

첫 시도는 41회 갱신 뒤 검증 코드가 Qwen attention의 실수형 scaling을 LoRA 사전으로 취급해 저장 전에 종료됐습니다. 해당 가중치는 남지 않았습니다. 원본 소스·실패 기록을 보존하고 LoRA 설정만 변경하도록 고친 뒤, 동일 초기값·자료·순서·옵티마이저로 41회를 다시 수행했습니다. 이미 만든 계산 자료 200개의 해시·ID·레이블을 검사해 재사용하고, 새 계산과의 일치와 학습 전 손실도 다시 확인했습니다. 최종 가중치에 반영된 갱신은 41회이며, 버려진 첫 시도의 41회를 합친 실제 계산은 82회였습니다. 재시도에서는 갱신 직후 가중치를 먼저 저장했습니다. [오류와 복구 계획](recovery/amendment.json), [원본 대비 수정](recovery/trainer-change.txt)을 포함했습니다. 학습된 후보의 생성 검증이나 최종 벤치 결과를 보기 전에 수정한 것입니다.

학습 전 원본 기준은 검증 업무 **4/12**, 기존 형식 유지 **1/12**, 기본 지시 수행 **8/8**이었습니다. 기존 형식 시험만으로 일반 능력을 판단할 수 없어, 가중치 갱신 전에 기본 계산·읽기·정렬 등 8개를 추가했습니다. 최초 선택 계획도 보존했습니다. 적용 강도0·0.5·1을 비교하되 업무·기존 형식·기본 지시 수행이 원본보다 떨어지는 후보는 채택하지 않는 기준을 사용했습니다. 이 8개가 광범위한 일반 능력 보존을 보장하지는 않습니다.

검증이 승인한 학습 모델: **{selection['validation_approved_learned_model']}**. 외부 평가에 사용한 실제 LoRA 강도: **{selection['evaluation_candidate']['strength']}**. 0이 선택되면 원본을 학습 모델로 바꾸어 부르지 않고, 최선의 양수 강도 후보를 거절된 실험 모델로만 따로 측정합니다. 외부 벤치 점수로 강도나 체크포인트를 고르지 않았습니다.

## 시험 범위

동일한 고정 v2.1 과제·최초 입력·도구 설명·채점, 8턴·턴당2048토큰·temperature0·seed719·8K문맥·6CPUthreads·같은 llama.cpp실행 파일과 Q4_K_M기반을 사용했습니다. CLI시간 제한도 유지했습니다. 모델 출력은 수정하지 않고 모의 도구에 전달했습니다. Windows stdin종료 오류 처리는 기존에 검증한 전송 수정본을 쓰며, v2.1업무 소스는 그대로 보존했습니다. 지원36개·환경차단9개,45개분모로 환경상 최대84.33점입니다.

새 값으로 만든 별도 가상 시험은 **{heldout['passed']}/24**개 통과입니다. 이전 나래1·2의 별도 시험과 값이 다르며 템플릿은 공유합니다. 이 수치를 벤치 점수와 합산하지 않았습니다. 공개 벤치와 개발자 사전 노출을 포함한 단일 seed시험이며 독립 의미 검수나 실제 학교 서비스 E2E가 아닙니다. 실서비스 동작은0회입니다.

별도 시험 24개 완료 후 공개 벤치 시작 코드의 `Path` import 누락으로, 공개 과제를 한 개도 실행하기 전에 중단됐습니다. 완료한 별도 시험을 보존하고 동일한 실제 모델·강도·실행 인자를 확인한 새 서버에서 원래 고정 벤치 worker를 직접 실행했습니다. 학습이나 별도 시험을 반복하지 않았고, 공개 벤치 과제·입력·예산·채점 코드는 그대로입니다. [시작 오류 복구 기록](recovery/benchmark-resume-amendment.json)을 함께 보관합니다.

별도 시험의 복무 준비 유형은 {heldout_by_kind['neis']['passed']}/6개였지만, 고정 공개 벤치의 나이스 영역은 {summary['domains']['NP-N']['passed']}/5개였습니다. 별도 시험의 한 가지 준비 흐름으로 나이스 전체 능력을 판단할 수 없습니다. 문서 작성도 별도 {heldout_by_kind['write']['passed']}/6개·고정 공개 벤치 {summary['domains']['NP-E-WXS-WRITE']['passed']}/4개였습니다.

현재 v2.2 CLI에서는 기존 계약 진단 3개(작성 `NP-E-WXS-WRITE-01`, 복무 `NP-N-03`, 대조 `NP-P-01`)를 설치된 로컬 실행기로 추가 확인했습니다. 결과는 **{report['current_cli_diagnostic']['passed']}/3개** 통과입니다. 이 과제들은 과거 실패를 분석하며 선택한 소수 진단이고, 나래3의 전체 벤치를 본 뒤 현재 도구 설명 차이를 확인한 후속 검사입니다. 전체 성능이나 블라인드 결과가 아니며 16.54점에 합산하지 않았습니다. LoRA 강도도 다시 선택하지 않았습니다. [계획과 소스 해시](current-cli/current-cli-plan.json), [검증](current-cli/current-cli-verification.json), 실제 요청·응답·도구 증거를 보관합니다.

## 로컬 사용과 공개 자료

실제 모델은 `D:\\Codex\\models\\Narae3`에 설치했습니다. [실행 안내 사본](local-runtime/README.md)은 로컬 경로를 설명합니다. 기존 설치된 브라우저나 모델 기본값을 자동 변경하지 않았습니다. 학습 자료·가중치·캐시·원본 로그는 `{ROOT}`와 D모델 폴더에 있습니다.

이번 모델은 실험판이며, 고정 모의 벤치의 원본 대비 점수가 낮아 개선 모델로 채택하지 않습니다. 로컬 실행기는 Windows 드라이브 문자와 `--lora-scaled` 구분자의 충돌을 상대 경로 사용으로 고쳤고, 실제 로드된 가중치 경로·강도·API 응답과 현재 CLI 3과제를 확인한 뒤 검사 서버를 종료했습니다.

이 공개 묶음에는 가상 평가 요청·응답·도구 증거, 코드와 해시·원본 라이선스·모델 메타데이터가 들어 있습니다. 가중치와 학습 원본은 포함하지 않습니다. recipe는 이 PC의 경로와 기존 합성 replay자료를 사용하는 사본이며, 다른PC의 학습 재현에는 해당 원본 자료와 의존성이 별도로 필요합니다. 다른 모델의 벤치 실행은 저장소 main의 CLI안내를 사용하세요.

원본: https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
'''
(DEST/'README.md').write_text(readme,encoding='utf-8')
dump(DEST/'manifest.json',{'type':'Actual Narae3 SFT and synthetic evaluation evidence; no weights or raw training records',
    'files':{p.relative_to(DEST).as_posix():sha(p) for p in sorted(DEST.rglob('*')) if p.is_file()}})
print(json.dumps({'report':str(DEST),'score':report['score'],'delta':report['delta_from_upstream'],'passed':report['passed']}))
