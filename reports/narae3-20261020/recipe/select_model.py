"""Select adaptation strength using predeclared generation validation and retention."""
from runtime import ROOT,load,dump,sha
plan=load(ROOT/'evaluation/selection-plan.json')
training=load(ROOT/'outputs/Narae3-Qwen3-4B-LoRA-v1/training-report.json')
candidates=[]
for tag,strength in [('base',0),('scale-050',.5),('scale-100',1)]:
    result=load(ROOT/'evaluation/validation'/tag/'results.json');assert result['complete']
    candidates.append({'tag':tag,'strength':strength,'tool_passed':result['tool_passed'],'retention_passed':result['retention_passed'],
        'general_probe_passed':load(ROOT/'evaluation/general'/tag/'results.json')['passed'],
        'failed_finishes':result['failed_finishes'],'length_limited_responses':result['length_limited_responses'],
        'teacher_loss':training['validation_losses_by_scale'][f'{strength:g}']})
base=candidates[0]
def key(r):return (r['tool_passed'],r['general_probe_passed'],r['retention_passed'],-r['failed_finishes'],-r['length_limited_responses'],-r['teacher_loss'],-r['strength'])
eligible=[r for r in candidates if r['tool_passed']>=base['tool_passed'] and r['retention_passed']>=base['retention_passed'] and r['general_probe_passed']>=base['general_probe_passed']]
selected=max(eligible,key=key)
# A rejected learned candidate can still be measured as an experiment, but never
# substitute the zero-scale original and call that a weight-trained Narae3.
evaluation=selected if selected['strength'] else max(candidates[1:],key=key)
selection={'complete':True,'selection_plan_sha256':sha(ROOT/'evaluation/selection-plan.json'),'candidates':candidates,
    'selected':selected,'validation_approved_learned_model':selected['strength']>0,
    'evaluation_candidate':evaluation,'benchmark_used_for_selection':False}
dump(ROOT/'outputs/selection.json',selection);print(selection)
