"""Summarize all existing result sets without pooling incompatible tracks."""
import collections
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REPO=Path('D:/Codex/workspaces/narae_bench')
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
a=read(ROOT/'before.json'); b=read(ROOT/'after.json')
rows=a['records']; all_runs=a['comparable_full_runs']
models=[]
for name,folder in all_runs.items():
    r=[x for x in rows if x['run']==name]
    summary=read(REPO/folder/'summary.json')
    models.append({'run':name,'full_profile':a['full_run_profile'],'score':summary['strict_e2e_score'],
                   'passed':sum(x['historical_status']=='PASS' for x in r),'executed':len(r),
                   'failures':sum(x['historical_status']!='PASS' for x in r)})
unfinished=[r for r in rows if 'finish' not in r['tools']]
malformed=[r for r in rows if any(t['result'].get('error','').startswith(('KeyError:', 'TypeError:', 'ValueError:', 'StopIteration:')) for t in r['tool_errors'])]
read_rows=[r for r in rows if r['case_id'] in ['NP-E-WXS-READ-02','NP-E-WXS-READ-05','NP-E-WXS-READ-06']]
facts_correct=[r for r in read_rows if 'facts' not in r['mismatched_report_fields']]
bad_citations=[r for r in facts_correct if 'sources' in r['mismatched_report_fields']]
keys=lambda rs:[{'run':r['run'],'case_id':r['case_id'],'evidence':r['evidence']} for r in rs]
changes=[{'run':r['run'],'case_id':r['case_id'],'old_checks':r['historical_checks'],'new_checks':r['replay_checks'],
          'fully_passes_on_replay':r['replay_pass'],'observations_unchanged':not r['observation_changes']} for r in b['records'] if r['checkset_changed']]
inventory=[]
for p in sorted((REPO/'reports').rglob('*results*.json')):
    if 'failure-audit-20261020' in p.parts:continue
    # Result-set files, not aggregate comparison/audit JSON.
    data=read(p)
    rs=data.get('results',data.get('cases',data.get('tool_results',[])+data.get('retention_results',[])))
    if not isinstance(rs,list) or not rs:continue
    relative=p.relative_to(REPO).as_posix()
    if any(relative==folder+'/results.json' for folder in all_runs.values()):track='comparable full v2.1'
    elif '/recovery/' in relative:track='recovery/interrupted; already represented in final runs, never pool'
    elif '/heldout/' in relative:track='different held-out tasks; separate dataset'
    elif '/validation/' in relative:track='validation for adapter strength selection; not test score'
    elif '/general/' in relative:track='different general-retention tasks; separate dataset'
    else:track='selected public diagnostics; not full-model score'
    statuses=collections.Counter(r.get('status','PASS' if r.get('passed') else 'FAIL') for r in rs)
    inventory.append({'path':relative,'track':track,'profile':data.get('profile'),'rows':len(rs),'statuses':dict(statuses)})
heldout=[]
for name,relative in [('narae1-v2','reports/tool-sft-v2-20261019/narae1/heldout/results.json'),
                      ('narae2-v2','reports/tool-sft-v2-20261019/narae2/heldout/results.json'),
                      ('narae3','reports/narae3-20261020/heldout/results.json')]:
    rs=read(REPO/relative)['results']
    by_kind={k:{'passed':sum(r['passed'] for r in rs if r['kind']==k),'total':sum(r['kind']==k for r in rs)} for k in sorted({r['kind'] for r in rs})}
    heldout.append({'run':name,'path':relative,'dataset_group':'narae3-new-private-24' if name=='narae3' else 'tool-sft-v2-shared-private-24','by_kind':by_kind})
private_first=[]
for model in ('narae1','narae2'):
    rs=[json.loads(line) for line in (REPO/f'reports/tool-sft-v2-20261019/{model}/heldout/transcript.jsonl').read_text(encoding='utf8').splitlines()]
    private_first.append({r['case_id']:r['request']['messages'] for r in rs if r['turn']==1})
assert len(private_first[0])==len(private_first[1])==24 and private_first[0]==private_first[1]
self_run=read(REPO/'reports/codex-self-20261019.json')
out={'type':'Evidence audit, not new model scores','models':models,'domains':a['domains'],'ranking':a['ranking'],
     'historical':{'executed':216,'passed':43,'failed':173,'failure_percent':round(173/216*100,2),
                   'blocked_per_run_excluded':9,'common_all_six_failures':sum(r['failures']==6 for r in a['ranking'])},
     'trace_findings':{'no_finish_count':len(unfinished),'no_finish_cases':keys(unfinished),
                       'eight_turn_no_finish_count':sum(len(r['tools'])==8 for r in unfinished),
                       'cases_with_argument_or_id_errors':len(malformed),'argument_or_id_error_cases':keys(malformed),
                       'read_fact_and_citation_tasks':len(read_rows),'facts_correct_but_citations_failed':keys(bad_citations),
                       'writing_cases_with_any_apply':sum('wxs.apply' in r['tools'] for r in rows if 'WXS-WRITE' in r['case_id']),
                       'attendance_ended_after_first_stale_response':sum(r['tools']==['neis.attendance','finish'] for r in rows if r['case_id']=='NP-N-01')},
     'replay':{'type':'same historical tool arguments and reports against changed services; counterfactual, not new inference',
               'passed_before':43,'passed_after':45,'changed_checks':changes,
               'cases_with_changed_observations':b['changed_observations'],'old_score_files_modified':False},
     'codex_assisted_reference':{k:self_run[k] for k in ['type','profile','strict_score','supported_passed','supported_cases','prior_benchmark_code_and_reference_exposure','comparison_to_small_model_tracks','failed_cases']},
     'result_inventory':inventory,'separate_heldout_kind_breakdown':heldout,
     'narae1_narae2_v2_private_identical_first_inputs':24,'live_service_actions':0,'weight_training_performed':False}
dump(ROOT/'comparison.json',out)
print(json.dumps({'model_runs':len(models),'result_sets_in_inventory':len(inventory),'unfinished':len(unfinished),
                  'argument_or_id_errors':len(malformed),'correct_facts_bad_citations':len(bad_citations)},ensure_ascii=False))
