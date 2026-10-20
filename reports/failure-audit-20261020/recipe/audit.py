"""Read immutable public runs, replay exact calls; no model inference or training."""
import argparse
import collections
import copy
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path('D:/Codex/workspaces/narae_bench')
WORK = Path(__file__).resolve().parent
RUNS = {
    'narae1-v1': 'reports/model-comparison-20261019/narae1',
    'narae2-v1': 'reports/model-comparison-20261019/narae2',
    'qwen4b-base': 'reports/model-comparison-20261019/qwen4b',
    'narae1-v2': 'reports/tool-sft-v2-20261019/narae1/benchmark',
    'narae2-v2': 'reports/tool-sft-v2-20261019/narae2/benchmark',
    'narae3': 'reports/narae3-20261020/benchmark',
}

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'mock/mock_workflow.py')
    parser.add_argument('--state', type=Path, default=WORK/'state')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    os.environ['NARAE_BENCH_STATE'] = str(args.state.resolve())
    sys.path.insert(0, str(ROOT/'mock'))
    spec = importlib.util.spec_from_file_location('audit_workflow', args.source)
    module = importlib.util.module_from_spec(spec)
    # Both frozen and current bytes resolve the same immutable fixture catalog.
    module.__file__ = str(ROOT/'mock/mock_workflow.py')
    spec.loader.exec_module(module)
    cases = {c['id']: c for c in module.CATALOG}
    records = []
    hashes = []
    for name, folder in RUNS.items():
        folder = ROOT/folder
        results = read(folder/'results.json')
        assert results['profile'] == 'high-level-mock-cli-v2.1'
        hashes.append({'path': (folder/'results.json').relative_to(ROOT).as_posix(), 'sha256': sha(folder/'results.json')})
        for row in results['results']:
            if row['status'] == 'BLOCKED':
                continue
            assert row['declared_supported'] and row['status'] in ('PASS', 'FAIL')
            cid = row['case_id']
            path = folder/'evidence'/f'{cid}.json'
            ev = read(path)
            assert ev['live_service_actions'] == 0
            hashes.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': sha(path)})
            w = module.World(cases[cid])
            observations = []
            for t in ev['trace']:
                result = w.call(t['tool'], copy.deepcopy(t['args']))
                result.pop('environment', None)
                if result != t['result']:
                    observations.append({'tool': t['tool'], 'historical': t['result'], 'replay': result})
            checks = w.grade()
            old = {k: v['pass'] for k, v in row['checks'].items()}
            report = ev.get('report') or {}
            mismatch = {k: {'reported': report.get(k), 'expected': v} for k,v in w.gold.items()
                        if module.norm(report.get(k)) != module.norm(v)}
            records.append({
                'run': name, 'case_id': cid, 'domain': cases[cid]['domain'],
                'historical_status': row['status'], 'historical_checks': old,
                'replay_checks': checks, 'checkset_changed': checks != old,
                'replay_pass': all(checks.values()) and not w.incidents,
                'observation_changes': observations,
                'failed_checks': [k for k,v in old.items() if not v],
                'mismatched_report_fields': mismatch,
                'tools': [t['tool'] for t in ev['trace']],
                'tool_errors': [t for t in ev['trace'] if not t['result'].get('ok')],
                'format_errors': ev.get('format_errors'),
                'incidents': row['incidents'],
                'evidence': path.relative_to(ROOT).as_posix(),
            })
    domains = []
    for domain in sorted({r['domain'] for r in records}):
        rs = [r for r in records if r['domain'] == domain]
        failures = sum(r['historical_status'] != 'PASS' for r in rs)
        domains.append({'domain': domain, 'trials': len(rs), 'failures': failures,
                        'failure_percent': round(100*failures/len(rs), 2),
                        'by_run': {n: sum(r['historical_status'] == 'PASS' for r in rs if r['run'] == n) for n in RUNS}})
    ranking = []
    for cid in sorted({r['case_id'] for r in records}):
        rs = [r for r in records if r['case_id'] == cid]
        ranking.append({'case_id': cid, 'domain': cases[cid]['domain'], 'name': cases[cid].get('name', cases[cid].get('title')),
                        'failures': sum(r['historical_status'] != 'PASS' for r in rs),
                        'trials': len(rs),
                        'passed_runs': [r['run'] for r in rs if r['historical_status'] == 'PASS']})
    ranking.sort(key=lambda r: (-r['failures'], r['case_id']))
    out = {'type': 'historical evidence comparison and exact-call replay; not new model inference',
           'source': str(args.source.resolve()), 'source_sha256': sha(args.source),
           'full_run_profile': 'high-level-mock-cli-v2.1', 'comparable_full_runs': RUNS,
           'executed_cases': len(records), 'blocked_cases_per_run_excluded': 9,
           'historical_passes': sum(r['historical_status'] == 'PASS' for r in records),
           'replay_passes': sum(r['replay_pass'] for r in records),
           'changed_checksets': sum(r['checkset_changed'] for r in records),
           'changed_observations': sum(bool(r['observation_changes']) for r in records),
           'domains': sorted(domains, key=lambda r: -r['failure_percent']),
           'ranking': ranking, 'records': records, 'input_hashes': hashes,
           'live_service_actions': 0, 'weight_training': False}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in out.items() if k not in ('records', 'input_hashes', 'comparable_full_runs')}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
