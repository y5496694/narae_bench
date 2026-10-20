"""Failure-audit controls: equivalent reports and invalid queries, no model scores."""
import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix='failure-contracts-', dir=ROOT/'work')
STATE = Path(TEMP.name)/'state'
subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'mock/cli.py'), 'prepare', '--out', str(STATE)],
               check=True, capture_output=True)
os.environ['NARAE_BENCH_STATE'] = str(STATE)
sys.path.insert(0, str(ROOT/'mock'))
from mock_workflow import World, CATALOG
spec = importlib.util.spec_from_file_location('model_bridge', ROOT/'mock/evaluate.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

def world(cid):
    return World(next(c for c in CATALOG if c['id'] == cid))

def perform(w):
    for tool,args in w.oracle[:-1]:
        w.call(tool, copy.deepcopy(args))

class FailureContracts(unittest.TestCase):
    def test_same_deadline_and_correction_action_are_equivalent(self):
        for cid in ('CBE-07', 'CBE-08'):
            for deadline in ('2026-11-24 15:00', '2026-11-24T15:00+09:00',
                             '2026.11.24T15:00', '2026-11-24T06:00Z'):
                with self.subTest(cid=cid, deadline=deadline):
                    w = world(cid); perform(w)
                    w.call('finish', {**w.gold, 'deadline': deadline, 'action': w.gold['action']+' 기한 정정'})
                    self.assertTrue(all(w.grade().values()))

    def test_wrong_deadlines_missing_time_and_negated_actions_still_fail(self):
        for field,values in {'deadline': ['2026-11-23 15:00', '2026-11-24', '2026-11-24T15:00Z', '2026-13-24 15:00'],
                             'action': ['참가 명단 제출 안 함', '참가 명단 제출 취소', '정정', 'notes']}.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    w = world('CBE-07'); perform(w)
                    w.call('finish', {**w.gold, field: value})
                    self.assertFalse(w.grade()['K3'])

    def test_unread_attachment_sets_have_no_required_sort_order(self):
        w = world('NP-E-WXS-READ-04'); perform(w)
        report = copy.deepcopy(w.gold)
        for k in ('unread_ids', 'content_unknown_ids'):
            report[k].reverse()
        w.call('finish', report)
        self.assertTrue(all(w.grade().values()))
        report['unread_ids'].append(report['unread_ids'][0])
        w.call('finish', report)
        self.assertFalse(w.grade()['K2'])

    def test_explicit_my_then_all_search_preserves_fallback_trace(self):
        w = world('CBE-02')
        first = w.call('cbe.search', {'name':'가상김','scope':'my'})
        self.assertEqual(first['users'], [])
        second = w.call('cbe.search', {'name':'가상김','scope':'all'})
        self.assertEqual(second['searched'], ['my','all'])
        self.assertTrue(second['fallback'])
        w.call('cbe.select', {'user_id':'U-KIM2'})
        w.call('cbe.search', {'name':'가상오류','scope':'auto'})
        w.call('finish', copy.deepcopy(w.gold))
        self.assertTrue(all(w.grade().values()))

    def test_search_error_does_not_fall_back_and_bad_scope_is_rejected(self):
        w = world('CBE-02')
        error = w.call('cbe.search', {'name':'가상오류','scope':'auto'})
        self.assertFalse(error['ok']); self.assertFalse(error['fallback'])
        self.assertEqual(error['searched'], ['my'])
        self.assertFalse(w.call('cbe.search', {'name':'가상김','scope':'my|all'})['ok'])

    def test_invalid_document_scope_enum_and_boolean_are_rejected(self):
        for changed in ({'scope':'my_documents|registry|circulation'}, {'date_basis':'processed|registered'},
                        {'all_pages':'true'}, {'scope':'registry','condition':'A|B|C'}, {'role':'drafted|received|approved'}):
            with self.subTest(changed=changed):
                w = world('NP-E-01')
                args = {**w.oracle[0][1], **changed}
                self.assertFalse(w.call('documents.query', args)['ok'])
                self.assertEqual(w.state['queries'], [])

    def test_circulation_wrong_date_and_title_cannot_pass_with_gold_report(self):
        for changed in ({'from':'2025-10-01'}, {'title_contains':'다른 검색어'}):
            with self.subTest(changed=changed):
                w = world('NP-E-06')
                for tool,args in w.oracle[:-1]:
                    w.call(tool, {**args, **changed} if tool=='documents.query' else args)
                w.call('finish', copy.deepcopy(w.gold))
                self.assertFalse(all(w.grade().values()))

    def test_registry_conditions_cannot_be_credited_under_wrong_scope(self):
        w = world('NP-E-05')
        for tool,args in w.oracle[:-1]:
            w.call(tool, {**args, 'scope':'circulation'})
        w.call('finish', copy.deepcopy(w.gold))
        self.assertFalse(all(w.grade().values()))

    def test_argument_schema_and_source_meaning_reach_model_without_answers(self):
        w = world('NP-E-01'); task = w.public()
        schema = bridge.public_schema(task)
        query = next(x['properties']['args'] for x in schema['oneOf']
                     if x['properties']['tool'].get('const') == 'documents.query')
        self.assertEqual(query['properties']['scope']['enum'], ['my_documents','registry','circulation'])
        self.assertEqual(query['properties']['all_pages']['type'], 'boolean')
        self.assertNotIn('MY-DRAFTED', str(schema))
        source = world('NP-E-WXS-READ-02').public()['finish_report_schema']['properties']['sources']
        self.assertIn('location', source['description'])
        self.assertNotIn('DOC-01:p1', str(source))

if __name__ == '__main__':
    unittest.main()
