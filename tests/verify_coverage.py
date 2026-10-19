"""Coverage semantics: complete observations, required filters, and truncated pages."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
(PACKAGE / "work").mkdir(exist_ok=True)
TEMP = tempfile.TemporaryDirectory(prefix="coverage-", dir=PACKAGE / "work")
STATE = Path(TEMP.name) / "state"
subprocess.run([sys.executable, "-X", "utf8", str(PACKAGE / "mock/cli.py"), "prepare", "--out", str(STATE)],
               check=True, capture_output=True)
os.environ["NARAE_BENCH_STATE"] = str(STATE)
sys.path.insert(0, str(PACKAGE / "mock"))
from mock_workflow import World, CATALOG


def world(case_id):
    return World(next(c for c in CATALOG if c["id"] == case_id))


class Coverage(unittest.TestCase):
    def test_complete_single_page_does_not_require_redundant_all_pages_flag(self):
        for case_id in ("NP-E-01", "NP-E-02", "NP-E-03", "NP-E-04"):
            for flag in (None, False, True):
                w = world(case_id)
                args = copy.deepcopy(w.oracle[0][1])
                if flag is None:
                    args.pop("all_pages")
                else:
                    args["all_pages"] = flag
                observed = w.call("documents.query", args)
                self.assertFalse(observed["has_more"])
                w.call("finish", copy.deepcopy(w.gold))
                self.assertTrue(all(w.grade().values()), (case_id, flag))

    def test_requesting_all_pages_does_not_override_observed_incomplete_coverage(self):
        w = world("NP-E-02")
        w.call(*copy.deepcopy(w.oracle[0]))
        w.trace[-1]["result"]["has_more"] = True
        w.call("finish", copy.deepcopy(w.gold))
        self.assertFalse(any(w.grade().values()))

    def test_required_date_role_and_drafter_filters_still_apply(self):
        for case_id, field in [("NP-E-01", "role"), ("NP-E-02", "date_basis"),
                               ("NP-E-03", "from"), ("NP-E-04", "drafter_id")]:
            w = world(case_id)
            args = copy.deepcopy(w.oracle[0][1])
            args.pop(field)
            w.call("documents.query", args)
            w.call("finish", copy.deepcopy(w.gold))
            self.assertFalse(any(w.grade().values()), (case_id, field))

    def test_truncated_multi_page_fixture_cannot_be_passed_with_guessed_ids(self):
        w = world("NP-E-05")
        for tool, args in w.oracle[:-1]:
            args = copy.deepcopy(args)
            args["all_pages"] = False
            w.call(tool, args)
        w.call("finish", copy.deepcopy(w.gold))
        self.assertFalse(w.grade()["K1"])
        self.assertFalse(w.grade()["K2"])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        TEMP.cleanup()
