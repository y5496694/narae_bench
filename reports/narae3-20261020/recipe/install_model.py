"""Create a real local Narae3 runtime after training and evaluation audit succeed."""
import json,shutil,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from runtime import ALIAS,EXE,EXE_SHA,load,dump,sha
audit=load(ROOT/'evaluation/verification.json');assert audit['verified'] and audit['benchmark_cases']==36
training=load(ROOT/'outputs'/ALIAS/'training-report.json');assert training['actual_weight_training']
selection=load(ROOT/'outputs/selection.json');scale=selection['evaluation_candidate']['strength'];assert scale>0
export=load(ROOT/'exports/verification.json');assert sha(export['file'])==export['export_sha256']
summary=load(ROOT/'evaluation/run/summary.json');result=load(ROOT/'evaluation/run/results.json')
serving=load(ROOT/'evaluation/serving/narae3-evaluation.json')
DEST=Path(r'D:\Codex\models\Narae3');DEST.mkdir(exist_ok=False)
shutil.copytree(ROOT/'outputs'/ALIAS/'adapter',DEST/'adapter')
shutil.copyfile(export['file'],DEST/Path(export['file']).name)
shutil.copyfile(Path(training['base_model']['path'])/'LICENSE',DEST/'LICENSE')
shutil.copyfile(ROOT/'models/source.json',DEST/'upstream-source.json')
created=datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')
metadata={'name':'나래3','served_model_id':ALIAS,'created_at':created,'training_root':str(ROOT),
    'base':serving['base'],'adapter':{'file':str(DEST/Path(export['file']).name),'sha256':export['export_sha256'],
       'safetensors_sha256':export['source_sha256'],'strength':scale},'native_executable':str(EXE),'executable_sha256':EXE_SHA,
    'actual_weight_training':True,'training_attempts':training['attempts'],'discarded_first_attempt_updates':41,
    'final_artifact_optimizer_updates':41,'validation_approved':selection['validation_approved_learned_model'],
    'mock_benchmark_score':summary['strict_e2e_score'],'mock_passed':sum(r['status']=='PASS' for r in result['results']),
    'historical_same_profile_upstream_score':20.92,
    'same_profile_mock_nonregression':selection['validation_approved_learned_model'] and summary['strict_e2e_score']>=20.92 and summary['critical_incident_cases']==0,
    'experimental':True,'experimental_reason':'Initial adapter with small synthetic training and limited mock validation; held-out workflow failures remain.'}
dump(DEST/'model.json',metadata)
(DEST/'NOTICE').write_text(f'Narae3: a LoRA derivative of Qwen/Qwen3-4B-Instruct-2507.\nUpstream revision: {training["base_model"]["revision"]}\nUpstream model authors: Qwen Team. License: Apache-2.0 (LICENSE retained).\nModified by local Narae supervised fine-tuning, {created}.\nThis is not a model trained from scratch; the original base is preserved.\n',encoding='utf-8')
launcher=r'''#Requires -Version 7.0
param([ValidateRange(1024,65535)][int]$Port=18462)
$ErrorActionPreference='Stop'
$m=Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'model.json') | ConvertFrom-Json
foreach($entry in @(@($m.base.file,$m.base.sha256),@($m.adapter.file,$m.adapter.sha256),@($m.native_executable,$m.executable_sha256))) {
    if((Get-FileHash -LiteralPath $entry[0] -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry[1]){throw 'Narae3 runtime file hash mismatch.'}
}
$runtimeRoot=Join-Path $PSScriptRoot 'runtime'
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
$env:TEMP=$runtimeRoot;$env:TMP=$runtimeRoot
$strength=([double]$m.adapter.strength).ToString([System.Globalization.CultureInfo]::InvariantCulture)
$adapterDirectory=[System.IO.Path]::GetDirectoryName($m.adapter.file)
$scaledAdapter='{0}:{1}' -f [System.IO.Path]::GetFileName($m.adapter.file),$strength
$nativeArgs=@('--model',$m.base.file,'--alias',$m.served_model_id,'--lora-scaled',$scaledAdapter,
    '--host','127.0.0.1','--port',[string]$Port,'--threads','6','--threads-batch','6','--ctx-size','8192','--parallel','1',
    '--batch-size','512','--ubatch-size','128','--cache-ram','0','--no-context-shift','--no-warmup','--no-webui',
    '--seed','719','--chat-template-kwargs','{"enable_thinking":false}')
Write-Host ('Narae3 : http://127.0.0.1:{0}/v1 ; model={1}' -f $Port,$m.served_model_id)
Write-Host ('Actual learned LoRA strength {0}; mock score {1}/100; experimental={2}' -f $strength,$m.mock_benchmark_score,$m.experimental)
$logFile=Join-Path $runtimeRoot ('server-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
Push-Location -LiteralPath $adapterDirectory
try { & $m.native_executable @nativeArgs 2>&1 | Tee-Object -FilePath $logFile }
finally { Pop-Location }
exit $LASTEXITCODE
'''
(DEST/'Start-Narae3.ps1').write_text(launcher,encoding='utf-8')
body=f'''# 나래3 · Qwen3-4B LoRA v1

Qwen3-4B-Instruct-2507에서 실제 가중치를 추가 학습한 로컬 모델입니다. 기반 모델 출처와 Apache-2.0 라이선스를 유지합니다. 프롬프트 이름만 바꾼 프로필이 아닙니다.

- 고정 v2.1 모의 벤치: **{summary['strict_e2e_score']:.2f}/100**, 지원 과제 **{metadata['mock_passed']}/36** 통과, 환경 차단 9개.
- 같은 조건의 Qwen 원본 기존 기록: **20.92점·12/36개**. 이번에는 기존 전체 원본 벤치를 재실행하지 않았습니다.
- 검증으로 선택한 실제 LoRA 적용 강도: **{scale}**. 실험 모델 상태: **{metadata['experimental']}**.
- 164개 대화·올바른 assistant 응답 362개, 1 epoch·41 optimizer step, rank 8·alpha 16, 마지막 6개 블록의 7개 선형 계층을 학습했습니다.
- 첫 시도는 갱신 41회 후 검증 코드 오류로 저장 전에 종료됐습니다. 같은 초기값·자료·조건으로 재시도했으며 최종 가중치에 반영된 갱신은 41회입니다. 실패한 시도의 41회와 복구 기록을 별도로 보존했습니다.
- 학습 원본·캐시·로그: `{ROOT}`. 모든 모델 자료는 D 드라이브에 있습니다.

## 실행

PowerShell 7에서 실행합니다. Ctrl+C로 종료합니다.

```powershell
pwsh -File D:\\Codex\\models\\Narae3\\Start-Narae3.ps1
```

OpenAI 호환 주소는 `http://127.0.0.1:18462/v1`, 모델 ID는 `{ALIAS}`입니다. 기본 Q4_K_M 모델은 기존 D 경로를 공유하고, 이 폴더의 검증된 실제 LoRA를 함께 적용합니다. Ollama 프롬프트 프로필을 대신 사용하는 방식이 아닙니다.

벤치는 가상 상태 검사이며 실제 학교 서비스 성공을 보장하지 않습니다. 학습·검증·시험은 별도 값으로 나누었으나 공개 벤치와 개발자의 사전 노출을 포함하므로 블라인드 시험은 아닙니다. 설치된 브라우저나 기존 모델 기본값을 자동 변경하지 않습니다.

원본: https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
'''
(DEST/'README.md').write_text(body,encoding='utf-8')
manifest={p.relative_to(DEST).as_posix():sha(p) for p in sorted(DEST.rglob('*')) if p.is_file()}
dump(DEST/'manifest.json',{'type':'Actual local Narae3 model runtime; weights stay on D','files':manifest})
dump(ROOT/'outputs/local-model.json',{'path':str(DEST),'metadata':metadata,'manifest_sha256':sha(DEST/'manifest.json')})
print(json.dumps({'installed_model':str(DEST),'actual_weight_training':True,'scale':scale}))
