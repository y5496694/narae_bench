"""Independent replay/identity/prompt audit of actual Narae3 calls and frozen scoring."""
import importlib.util,json,sys
import numpy as np
from safetensors.numpy import load_file
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from runtime import load,dump,sha,ALIAS,EXE_SHA
from tool_corpus import World,dumps
from general_probe import PROBES
spec=importlib.util.spec_from_file_location('audit_bridge',ROOT/'evaluation/controller.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
def lines(path):return [json.loads(s) for s in Path(path).read_text(encoding='utf-8').splitlines()]
def check_response(entry,alias,tokens):
    q,r=entry['request'],entry['response']
    assert q['model']==r['model']==alias and q['temperature']==0 and q['seed']==719 and q['stream'] is False
    assert q['max_tokens']==tokens and 0<=r['usage']['completion_tokens']<=tokens and r['usage']['prompt_tokens']<=8192
def replay(row,entries,alias,turns,tokens):
    w=World(row['scenario']);messages=[{'role':'system','content':bridge.SYSTEM},{'role':'user','content':dumps(row['scenario']['task'])}]
    if row['scenario']['bad_prefix']:
        tool,args=row['scenario']['bad_prefix'];obs=w.call(tool,args)
        messages += [{'role':'assistant','content':dumps({'tool':tool,'args':args})},{'role':'user','content':dumps({'event':'observation','result':{'environment':'mock',**obs}})}]
    es=[e for e in entries if e['case_id']==row['id']];assert 1<=len(es)<=turns
    for e in es:
        check_response(e,alias,tokens);assert e['request']['messages']==messages
        assert e['request']['response_format']['json_schema']['schema']==bridge.public_schema(row['scenario']['task'])
        text=e['response']['choices'][0]['message'].get('content')
        try:call=bridge.parse_reply(text);obs=w.call(call['tool'],call['args'])
        except (TypeError,ValueError):obs={'ok':False,'error':'INVALID_TOOL_JSON'}
        assert obs==e['observation']
        messages += [{'role':'assistant','content':text or ''},{'role':'user','content':dumps({'event':'observation','result':{'environment':'mock',**obs}})}]
    return w

profile=load(ROOT/'frozen-training-profile.json')
for name,digest in profile['source_sha256'].items():assert sha(ROOT/name)==digest,name
ids={split:{r['id'] for r in lines(ROOT/'data'/f'{split}.jsonl')} for split in ['train','validation','test']}
assert not ids['train']&ids['validation'] and not ids['train']&ids['test'] and not ids['validation']&ids['test']
assert profile['epochs']==1 and profile['optimizer_steps']==41 and profile['baseline_validation_completed_before_training']
for name,digest in load(ROOT/'evaluation/snapshot.json')['files_sha256'].items():assert sha(ROOT/'evaluation/benchmark'/name)==digest
training=load(ROOT/'outputs'/ALIAS/'training-report.json');export=load(ROOT/'exports/verification.json')
assert training['actual_weight_training'] and training['optimizer_steps']==41
amendment=load(ROOT/'recovery/amendment.json')
assert amendment['frozen_original_profile_sha256']==sha(ROOT/'frozen-training-profile.json')
assert not amendment['adapted_native_validation_or_public_results_observed']
for name,digest in amendment['recovery_source_sha256'].items():assert sha(ROOT/name)==digest,name
for name,digest in amendment['first_attempt_evidence_sha256'].items():assert sha(ROOT/name)==digest,name
for name,digest in load(ROOT/'recovery/cache-manifest.json')['files'].items():assert sha(ROOT/name)==digest,name
assert training['recovery_amendment_sha256']==sha(ROOT/'recovery/amendment.json')
assert training['trainer_source_sha256']==sha(ROOT/'recovery/train_lora_recovery.py')
assert training['attempts']==2 and training['discarded_first_attempt_updates']==41 and training['final_artifact_optimizer_updates']==41
assert training['cached_prefix_recovery_max_error']<=2e-4 and not training['first_attempt_weights_saved']
benchmark_resume=load(ROOT/'recovery/benchmark-resume-amendment.json')
assert benchmark_resume['completed_heldout_cases_preserved']==24 and benchmark_resume['public_cases_executed_before_resume']==0
assert sha(ROOT/'recovery/resume_benchmark.py')==benchmark_resume['resume_source_sha256']
for name,digest in benchmark_resume['preserved_artifacts_sha256'].items():assert sha(ROOT/name)==digest,name
first_updates=[r for r in lines(ROOT/'recovery/attempt-1/output/events.jsonl') if r['stage']=='training']
final_updates=[r for r in lines(ROOT/'outputs'/ALIAS/'events.jsonl') if r['stage']=='training']
assert [r['optimizer_step'] for r in first_updates]==[r['optimizer_step'] for r in final_updates]==list(range(1,42))
repeated_loss_error=max(abs(a['mean_loss']-b['mean_loss']) for a,b in zip(first_updates,final_updates))
assert repeated_loss_error<=2e-4
assert load(ROOT/'outputs'/ALIAS/'post-update-checkpoint.json')['adapter_file_sha256']==training['adapter_file_sha256']
assert len(training['adapter_parameter_l2_changes'])==84 and all(v>0 for v in training['adapter_parameter_l2_changes'].values())
assert training['future_token_causality_max_error']<=2e-4 and training['cached_vs_full_loss_absolute_error']<=2e-4
assert training['sdpa_vs_eager_loss_absolute_error']<=2e-4
assert sha(ROOT/'outputs'/ALIAS/'adapter/adapter_model.safetensors')==export['source_sha256']==training['adapter_file_sha256']
assert sha(export['file'])==export['export_sha256'] and export['all_f32_tensors_bitwise_equal'] and export['tensors']==84
initial=load_file(ROOT/'outputs'/ALIAS/'initial-adapter/adapter_model.safetensors')
learned=load_file(ROOT/'outputs'/ALIAS/'adapter/adapter_model.safetensors')
assert initial.keys()==learned.keys() and len(learned)==84
for name,value in learned.items():
    assert np.isfinite(value).all() and np.any(value!=initial[name]),name
    if '.lora_B.' in name:assert not np.count_nonzero(initial[name])
selection=load(ROOT/'outputs/selection.json');plan=load(ROOT/'evaluation/selection-plan.json')
assert selection['selection_plan_sha256']==sha(ROOT/'evaluation/selection-plan.json') and plan['version']==2
validation_rows=lines(ROOT/'data/validation-trajectories.jsonl');retention_rows=[r for r in lines(ROOT/'data/validation.jsonl') if r['kind'].startswith('replay_')]
counts={'validation_tool_cases':0,'legacy_retention_cases':0,'general_probe_cases':0,'heldout_cases':0,'benchmark_cases':0}
for tag,strength in [('base',None),('scale-050',.5),('scale-100',1)]:
    serving=load(ROOT/'evaluation/serving'/f'{tag}.json');alias=serving['alias']
    assert serving['executable_sha256']==EXE_SHA and serving['scale']==strength
    if strength is None:assert not serving['actual_narae_weight_training'] and not serving['loaded_adapters']
    else:assert serving['actual_narae_weight_training'] and serving['loaded_adapters'][0]['scale']==strength
    prefix=load(ROOT/'evaluation/validation'/tag/'prefix-verification.json');assert prefix['native_prompt_and_tokens_equal_hf'] and len(prefix['checks'])==8
    result=load(ROOT/'evaluation/validation'/tag/'results.json');entries=lines(ROOT/'evaluation/validation'/tag/'transcript.jsonl')
    successes=0
    for case_id in plan['tool_case_ids']:
        row=next(r for r in validation_rows if r['id']==case_id);w=replay(row,entries,alias,6,768)
        grade=next(r for r in result['tool_results'] if r['id']==case_id)
        assert w.passed()==grade['passed'] and w.report==grade['report'];successes+=w.passed();counts['validation_tool_cases']+=1
        assert grade['failed_finish']==bool(w.report is not None and not w.passed())
    assert successes==result['tool_passed']
    assert result['failed_finishes']==sum(r['failed_finish'] for r in result['tool_results'])
    assert result['length_limited_responses']==sum(e['response']['choices'][0]['finish_reason']=='length' for e in entries if 'turn' in e)
    correct=0
    for row in retention_rows:
        entry=next(e for e in entries if e['case_id']==row['id']);check_response(entry,alias,256)
        assert entry['request']['messages']==row['messages'][:-1]
        text=(entry['response']['choices'][0]['message'].get('content') or '').strip();expected=row['messages'][-1]['content'].strip()
        try:passed=json.loads(text)==json.loads(expected) if row['kind']=='replay_route' else text==expected
        except (ValueError,TypeError):passed=False
        assert passed==entry['passed'];correct+=passed;counts['legacy_retention_cases']+=1
    assert correct==result['retention_passed']
    general=load(ROOT/'evaluation/general'/tag/'results.json');general_entries=lines(ROOT/'evaluation/general'/tag/'transcript.jsonl');correct=0
    general_serving=load(ROOT/'evaluation/serving'/f'general-{tag}.json')
    assert general_serving['alias']==alias and general_serving['scale']==strength and general_serving['loaded_adapters']==serving['loaded_adapters']
    for identifier,prompt,expected,is_json in PROBES:
        entry=next(e for e in general_entries if e['id']==identifier);check_response(entry,alias,128)
        assert entry['request']['messages']==[{'role':'system','content':'사용자가 요청한 형식과 원문을 정확히 따르세요.'},{'role':'user','content':prompt}]
        text=(entry['response']['choices'][0]['message'].get('content') or '').strip()
        try:passed=json.loads(text)==json.loads(expected) if is_json else text==expected
        except (ValueError,TypeError):passed=False
        assert passed==entry['passed'];correct+=passed;counts['general_probe_cases']+=1
    assert correct==general['passed']
    candidate=next(c for c in selection['candidates'] if c['tag']==tag)
    assert candidate['tool_passed']==successes and candidate['retention_passed']==result['retention_passed'] and candidate['general_probe_passed']==correct
    assert candidate['teacher_loss']==training['validation_losses_by_scale'][f'{0 if strength is None else strength:g}']
base=selection['candidates'][0]
def rank(r):return (r['tool_passed'],r['general_probe_passed'],r['retention_passed'],-r['failed_finishes'],-r['length_limited_responses'],-r['teacher_loss'],-r['strength'])
eligible=[r for r in selection['candidates'] if r['tool_passed']>=base['tool_passed'] and r['retention_passed']>=base['retention_passed'] and r['general_probe_passed']>=base['general_probe_passed']]
assert selection['selected']==max(eligible,key=rank) and not selection['benchmark_used_for_selection']
serving=load(ROOT/'evaluation/serving/narae3-evaluation.json')
assert serving==load(ROOT/'evaluation/serving/narae3-public-resume.json')
assert serving['alias']==ALIAS and serving['scale']==selection['evaluation_candidate']['strength']>0
assert serving['adapter']['source_sha256']==export['source_sha256'] and serving['loaded_adapters'][0]['scale']==serving['scale']
heldout=load(ROOT/'evaluation/heldout/results.json');entries=lines(ROOT/'evaluation/heldout/transcript.jsonl')
assert heldout['complete'] and heldout['planned']==24 and len(heldout['results'])==24
assert heldout['passed']==sum(r['passed'] for r in heldout['results'])
for row in lines(ROOT/'data/test-trajectories.jsonl'):
    w=replay(row,entries,ALIAS,8,2048);grade=next(r for r in heldout['results'] if r['id']==row['id'])
    assert w.passed()==grade['passed'] and w.report==grade['report'];counts['heldout_cases']+=1
folder=ROOT/'evaluation/run';result=load(folder/'results.json');summary=load(folder/'summary.json')
assert summary['all_cases_completed'] and summary['not_run']==0 and not (folder/'controller-error.json').exists()
assert sum(r['status']=='BLOCKED' for r in result['results'])==9
entries=lines(folder/'model-transcript.jsonl')
old=lines(Path(r'D:\Codex\benchmarks\narae-compare-v21-20261019/api-runs/qwen4b/model-transcript.jsonl'))
for row in result['results']:
    if row['status'] not in ['PASS','FAIL']:continue
    es=[e for e in entries if e['case_id']==row['case_id']];prior=next(e for e in old if e['case_id']==row['case_id'] and e['turn']==1)
    assert 1<=len(es)<=8 and es[0]['request']['messages']==prior['request']['messages'] and es[0]['request']['response_format']==prior['request']['response_format']
    evidence=load(folder/'evidence'/f'{row["case_id"]}.json');index=0
    for e in es:
        check_response(e,ALIAS,2048)
        if e['observation']['event']=='closed':assert row['failure_layer']=='TIMEOUT';continue
        try:call=bridge.parse_reply(e['response']['choices'][0]['message'].get('content'))
        except (ValueError,TypeError):continue
        actual=evidence['trace'][index];assert call=={'tool':actual['tool'],'args':actual['args']}
        assert {k:v for k,v in e['observation']['result'].items() if k!='environment'}==actual['result'];index+=1
    assert index==len(evidence['trace']) and evidence['live_service_actions']==0;counts['benchmark_cases']+=1
assert counts=={'validation_tool_cases':36,'legacy_retention_cases':36,'general_probe_cases':24,'heldout_cases':24,'benchmark_cases':36}
audit={'verified':True,**counts,'same_public_initial_messages_and_schema_as_upstream_4b':True,'actual_weight_training_and_loaded_scale_verified':True,
       'source_and_budget_checks_passed':True,'responses_forwarded_unchanged':True,'live_service_actions':0,
       'documented_posttraining_failure_recovery_verified':True,'discarded_first_attempt_updates':41,
       'final_artifact_optimizer_updates':41,'repeat_update_mean_loss_max_error':repeated_loss_error,
       'benchmark_startup_recovery_preserved_heldout_and_identical_server':True}
dump(ROOT/'evaluation/verification.json',audit);print(json.dumps(audit))
