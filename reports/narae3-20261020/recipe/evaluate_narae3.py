"""Unseen synthetic values and frozen v2.1 public benchmark; no output repairs."""
import importlib.util,json,os,subprocess,sys,time
from types import SimpleNamespace
from runtime import ROOT,ALIAS,Server,load,dump,sha
from validate_native import evaluate_episode

def worker():
    spec=importlib.util.spec_from_file_location('frozen_bridge',ROOT/'evaluation/controller.py')
    bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
    bridge.PACKAGE=ROOT/'evaluation/benchmark'
    bridge.run(SimpleNamespace(base_url='http://127.0.0.1:18464/v1',model=ALIAS,out=ROOT/'evaluation/run',
        format='schema',max_tokens=2048,request_timeout=600,case=None))

def main():
    selection=load(ROOT/'outputs/selection.json');assert selection['complete']
    snapshot=load(ROOT/'evaluation/snapshot.json')
    for name,digest in snapshot['files_sha256'].items():assert sha(ROOT/'evaluation/benchmark'/name)==digest
    strength=selection['evaluation_candidate']['strength'];assert strength>0
    server=Server('narae3-evaluation',strength)
    try:
        private=ROOT/'evaluation/heldout';private.mkdir(exist_ok=False)
        rows=[json.loads(s) for s in (ROOT/'data/test-trajectories.jsonl').read_text(encoding='utf-8').splitlines()]
        results=[]
        with (private/'transcript.jsonl').open('x',encoding='utf-8') as log:
            for row in rows:
                results.append(evaluate_episode(row,ALIAS,8,2048,log))
                dump(ROOT/'evaluation/status.json',{'stage':'heldout','completed':len(results),'planned':24,'passed':sum(r['passed'] for r in results)})
        dump(private/'results.json',{'complete':True,'passed':sum(r['passed'] for r in results),'planned':24,'results':results,
             'scope':'New held-out values from shared synthetic templates; not the old v2 private cases or live services.'})
        path=ROOT/'evaluation/logs/benchmark.log'
        with path.open('wb') as log:
            child=subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__)),'--worker'],stdout=log,stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            while child.poll() is None:
                text=path.read_text(encoding='utf-8')
                dump(ROOT/'evaluation/status.json',{'stage':'benchmark','completed':text.count('"case_completed":'),'planned':36})
                time.sleep(2)
            if child.returncode:raise RuntimeError('Benchmark controller failed; preserve partial artifacts and inspect benchmark.log')
        summary=load(ROOT/'evaluation/run/summary.json')
        assert summary['all_cases_completed'] and summary['not_run']==0
        dump(ROOT/'evaluation/status.json',{'stage':'complete','score':summary['strict_e2e_score']})
        print(json.dumps({'model':ALIAS,'scale':strength,'strict_score':summary['strict_e2e_score'],'heldout_passed':sum(r['passed'] for r in results)}),flush=True)
    finally:server.close()
if __name__=='__main__':worker() if '--worker' in sys.argv else main()
