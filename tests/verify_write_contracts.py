"""Writing-grader regression tests; these controls are not model scores."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PACKAGE=Path(__file__).resolve().parents[1]
(PACKAGE/'work').mkdir(exist_ok=True)
TEMP=tempfile.TemporaryDirectory(prefix='write-contract-',dir=PACKAGE/'work')
STATE=Path(TEMP.name)/'run'
subprocess.run([sys.executable,'-X','utf8',str(PACKAGE/'mock/cli.py'),'prepare','--out',str(STATE)],
               check=True,capture_output=True)
os.environ['NARAE_BENCH_STATE']=str(STATE)
sys.path.insert(0,str(PACKAGE/'mock'))
from mock_workflow import World,CATALOG


def execute(case_id,edit=None):
    w=World(next(c for c in CATALOG if c['id']==case_id))
    for tool,args in w.oracle:
        args=copy.deepcopy(args)
        if edit and tool=='wxs.apply':edit(args['fields'],w.task)
        result=w.call(tool,args)
        assert result['ok'],result
    return w


class WritingContracts(unittest.TestCase):
    def test_valid_single_multiple_and_no_attachment_controls(self):
        for number in range(1,5):
            with self.subTest(number=number):
                self.assertTrue(all(execute(f'NP-E-WXS-WRITE-{number:02d}').grade().values()))

    def test_wrong_attachment_label_quantity_and_number_are_rejected(self):
        variants=['붙임  다른 문서 999부.  끝.','붙임  {label} 2부.  끝.',
                  '붙임  7. {label} 1부.  끝.']
        for suffix in variants:
            def edit(fields,task):
                fields['body']=fields['body'].split('\n\n붙임  ',1)[0]+'\n\n'+suffix.format(label=task['attachments'][0]['label'])
            with self.subTest(suffix=suffix):
                w=execute('NP-E-WXS-WRITE-01',edit)
                self.assertTrue(w.grade()['K7'])
                self.assertFalse(w.grade()['K8'])

    def test_multiple_attachments_require_each_label_quantity_and_number(self):
        def omit_number(fields,task):
            fields['body']=fields['body'].replace('붙임  1. ','붙임  ')
        self.assertFalse(execute('NP-E-WXS-WRITE-02',omit_number).grade()['K8'])

    def test_recovery_accepts_windows_line_endings(self):
        def crlf(fields,task):fields['body']=fields['body'].replace('\n','\r\n')
        self.assertTrue(all(execute('NP-E-WXS-WRITE-04',crlf).grade().values()))

    def test_recovery_still_rejects_changed_content_and_missing_attachment(self):
        for key,value in [('body','본문 사실을 지운 내용'),('attachments',[])]:
            def edit(fields,task):fields[key]=value
            with self.subTest(key=key):
                w=execute('NP-E-WXS-WRITE-04',edit)
                self.assertFalse(w.grade()['K2'])
                self.assertFalse(w.grade()['K4'])


if __name__=='__main__':
    try:unittest.main()
    finally:TEMP.cleanup()
