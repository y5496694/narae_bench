"""Exercise the installed PowerShell launcher and stop only its own native child."""
import json,os,shutil,socket,subprocess,sys,time,urllib.request
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from runtime import ALIAS,EXE,EXE_SHA,dump,load,sha
DEST=Path(r'D:\Codex\models\Narae3');PORT=18462
def event(stage,**values):print(json.dumps({'stage':stage,**values}),flush=True)
def request(route,payload=None,timeout=15):
    data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8')
    req=urllib.request.Request(f'http://127.0.0.1:{PORT}'+route,data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)

assert load(ROOT/'evaluation/verification.json')['verified']
metadata=load(DEST/'model.json');assert metadata['actual_weight_training'] and metadata['adapter']['strength']>0
manifest=load(DEST/'manifest.json')
for name,digest in manifest['files'].items():assert sha(DEST/name)==digest,name
for name,digest in [(metadata['base']['file'],metadata['base']['sha256']),
                    (metadata['adapter']['file'],metadata['adapter']['sha256']),
                    (metadata['native_executable'],EXE_SHA)]:assert sha(name)==digest
with socket.socket() as probe:probe.bind(('127.0.0.1',PORT))
pwsh=shutil.which('pwsh');assert pwsh,'PowerShell 7 unavailable'
launcher=DEST/'Start-Narae3.ps1'
env=os.environ.copy();env.update({'TEMP':str(ROOT/'tmp'),'TMP':str(ROOT/'tmp'),'TMPDIR':str(ROOT/'tmp'),
                                'NARAE_PS1':str(launcher)})
(ROOT/'tmp').mkdir(exist_ok=True)
parse=subprocess.run([pwsh,'-NoProfile','-NonInteractive','-Command',
    '$tokens=$null;$parseErrors=$null;[System.Management.Automation.Language.Parser]::ParseFile($env:NARAE_PS1,[ref]$tokens,[ref]$parseErrors)|Out-Null;if($parseErrors.Count){$parseErrors|ForEach-Object{$_.Message};exit 1}'],
    env=env,capture_output=True,text=True,encoding='utf-8',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
assert parse.returncode==0,parse.stderr+parse.stdout
event('launcher-parsed',port=PORT)
log=ROOT/'logs/installed-launcher.log';native=None;native_identity=None
with log.open('ab') as output:
    command=[pwsh,'-NoProfile','-NonInteractive','-File',str(launcher),'-Port',str(PORT)]
    process=subprocess.Popen(command,env=env,stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW)
    parent=psutil.Process(process.pid)
    try:
        start=time.monotonic()
        while True:
            if process.poll() is not None:raise RuntimeError('Installed launcher exited; inspect D launcher log')
            try:
                if request('/health',timeout=3).get('status')=='ok':break
            except (OSError,TimeoutError):pass
            if time.monotonic()-start>180:raise TimeoutError('Installed model startup timeout')
            time.sleep(.5)
        natives=[p for p in parent.children(recursive=True) if Path(p.exe()).resolve()==EXE.resolve()]
        assert len(natives)==1
        native=natives[0];native_identity={'pid':native.pid,'create_time':native.create_time(),'executable':native.exe(),'command':native.cmdline(),'cwd':native.cwd()}
        listeners=[c for c in native.net_connections(kind='tcp') if c.status==psutil.CONN_LISTEN and c.laddr.port==PORT]
        assert listeners and all(c.laddr.ip=='127.0.0.1' for c in listeners)
        models=request('/v1/models');assert ALIAS in [m['id'] for m in models['data']]
        adapters=request('/lora-adapters')
        assert len(adapters)==1 and adapters[0]['scale']==metadata['adapter']['strength']
        loaded_path=Path(adapters[0]['path'])
        if not loaded_path.is_absolute():loaded_path=Path(native.cwd())/loaded_path
        assert loaded_path.resolve()==Path(metadata['adapter']['file']).resolve()
        event('installed-learned-adapter-loaded',scale=adapters[0]['scale'],native_pid=native.pid)
        payload={'model':ALIAS,'messages':[{'role':'user','content':'7 더하기 8은? 숫자만 답하세요.'}],
                 'max_tokens':32,'temperature':0,'seed':719,'stream':False}
        response=request('/v1/chat/completions',payload,timeout=300)
        assert response['model']==ALIAS and response['choices'][0]['message'].get('content')
        assert response['usage']['completion_tokens']<=32
        event('installed-model-answered')
        # Reuse the three previously published contract diagnostics on current v2.2.
        # This is a partial integration check, never a replacement full score.
        repo=Path(r'D:\Codex\workspaces\narae_bench')
        case_ids=['NP-E-WXS-WRITE-01','NP-N-03','NP-P-01']
        current_sources=['bench.py','cases.json','mock/cli.py','mock/mock_workflow.py','mock/evaluate.py']
        source_hashes={name:sha(repo/name) for name in current_sources}
        plan={'scope':'Three existing v2.2 contract diagnostics, selected before this model run; partial check only',
              'case_ids':case_ids,'model':ALIAS,'strength':metadata['adapter']['strength'],
              'source_sha256':source_hashes,'used_for_model_selection':False,'added_to_v21_full_score':False}
        dump(ROOT/'outputs/current-cli-plan.json',plan)
        diagnostic_out=ROOT/'evaluation/current-cli'
        diagnostic_command=[sys.executable,'-X','utf8',str(repo/'mock/evaluate.py'),
            '--base-url',f'http://127.0.0.1:{PORT}/v1','--model',ALIAS,'--out',str(diagnostic_out)]
        for identifier in case_ids:diagnostic_command+=['--case',identifier]
        with (ROOT/'logs/installed-current-cli.log').open('xb') as diagnostic_log:
            event('current-cli-diagnostic-started',planned=3)
            subprocess.run(diagnostic_command,env=env,stdout=diagnostic_log,stderr=diagnostic_log,
                           check=True,timeout=2100,creationflags=subprocess.CREATE_NO_WINDOW)
        for name,digest in source_hashes.items():assert sha(repo/name)==digest
        diagnostic=load(diagnostic_out/'results.json')
        executed=[r for r in diagnostic['results'] if r['status'] in ['PASS','FAIL']]
        assert {r['case_id'] for r in executed}==set(case_ids) and len(executed)==3
        assert not (diagnostic_out/'controller-error.json').exists()
        import importlib.util
        spec=importlib.util.spec_from_file_location('current_cli_audit',repo/'mock/evaluate.py')
        current_bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(current_bridge)
        calls=[json.loads(s) for s in (diagnostic_out/'model-transcript.jsonl').read_text(encoding='utf-8').splitlines()]
        for row in executed:
            evidence=load(diagnostic_out/'evidence'/f'{row["case_id"]}.json');index=0
            entries=[c for c in calls if c['case_id']==row['case_id']];assert 1<=len(entries)<=8
            for entry in entries:
                q,r=entry['request'],entry['response']
                assert q['model']==r['model']==ALIAS and q['max_tokens']==2048 and q['temperature']==0 and q['seed']==719
                assert q['stream'] is False and r['usage']['completion_tokens']<=2048
                if entry['observation']['event']=='closed':assert row['failure_layer']=='TIMEOUT';continue
                try:call=current_bridge.parse_reply(r['choices'][0]['message'].get('content'))
                except (ValueError,TypeError):continue
                actual=evidence['trace'][index]
                assert call=={'tool':actual['tool'],'args':actual['args']}
                assert {k:v for k,v in entry['observation']['result'].items() if k!='environment'}==actual['result']
                index+=1
            assert index==len(evidence['trace']) and evidence['live_service_actions']==0
        current_check={'verified':True,'planned':3,'executed':3,'passed':sum(r['status']=='PASS' for r in executed),
                       'results':[{'id':r['case_id'],'status':r['status']} for r in executed],
                       'plan_sha256':sha(ROOT/'outputs/current-cli-plan.json'),'full_v21_score_unchanged':True}
        dump(ROOT/'outputs/current-cli-verification.json',current_check)
        event('current-cli-diagnostic-complete',passed=current_check['passed'],planned=3)
    finally:
        # Terminate descendants only after proving they belong to this exact launcher.
        if process.poll() is None:
            children=parent.children(recursive=True)
            for child in children:
                assert child.parent() is not None
                assert parent.pid in [p.pid for p in child.parents()]
            for child in reversed(children):
                try:child.terminate()
                except psutil.NoSuchProcess:pass
            _,alive=psutil.wait_procs(children,timeout=10)
            for child in alive:
                try:child.kill()
                except psutil.NoSuchProcess:pass
            psutil.wait_procs(alive,timeout=10)
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
assert native_identity is not None
assert not psutil.pid_exists(native_identity['pid']) or psutil.Process(native_identity['pid']).create_time()!=native_identity['create_time']
with socket.socket() as probe:probe.bind(('127.0.0.1',PORT))
verification={'verified':True,'launcher_sha256':sha(launcher),'model_manifest_sha256':sha(DEST/'manifest.json'),
    'powershell_parser_passed':True,'actual_learned_adapter_loaded':True,'loaded_adapters':adapters,
    'models':models,'native_process':native_identity,'command':command,'request':payload,'response':response,
    'port':PORT,'own_server_stopped':True,'port_released':True,'live_service_actions':0,'current_cli_diagnostic':current_check,
    'scope':'Installed local launcher integration check; not a benchmark score'}
dump(ROOT/'outputs/launcher-verification.json',verification);event('launcher-verified-and-stopped')
