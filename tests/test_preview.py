"""Release contract regressions and a runner implemented without Python."""
import os
import json
import shutil
from pathlib import Path

import pytest

from closure.engine import Engine, approve_baseline
from closure.io import ClosureError, canonical, digest
from closure.project import Project
from conftest import edit_yaml

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize('vector', json.loads((ROOT/'conformance/canonical.json').read_text(encoding='utf-8')), ids=lambda v:v['name'])
def test_portable_canonical_vectors(vector):
    value = json.loads(vector['input'])
    assert canonical(value) == vector['canonical'].encode('utf-8')
    assert digest(value) == vector['sha256']


def test_artifact_criteria_cannot_pass_by_comparing_absent_scalar_values(project_dir):
    edit_yaml(project_dir/'model/power.yaml', lambda d: (
        d['parameters'].update(left={'type':'artifact','path':'left.bin'}, right={'type':'artifact','path':'right.bin'}),
        d['requirements']['PWR-001'].update(verify={'actual':{'ref':'power.left'},'op':'eq','limit':{'ref':'power.right'}})))
    with pytest.raises(ClosureError, match='Compare artifacts') as failure:
        Project(project_dir)
    assert failure.value.code == 'TYPE_MISMATCH'


def test_javascript_runner_propagates_changes_without_importing_closure(tmp_path):
    node = os.environ.get('CLOSURE_TEST_NODE') or shutil.which('node')
    if not node:
        pytest.skip('Node is required for the cross-language release check')
    shutil.copytree(ROOT/'conformance/javascript-project', tmp_path, dirs_exist_ok=True)
    edit_yaml(tmp_path/'model/power.yaml', lambda d: d['analyses']['budget']['run']['argv'].__setitem__(0, node))
    approve_baseline(Project(tmp_path), 'Conformance fixture', 'Synthetic test obligation')
    first = Engine(tmp_path).verify(trusted=True)
    assert first['gate'] and first['values']['power.budget.total']['value'] == 180
    assert Engine(tmp_path).verify(trusted=True)['executed'] == []
    edit_yaml(tmp_path/'model/power.yaml', lambda d: d['parameters']['load'].update(value=120))
    assert Engine(tmp_path).plan()['requirements'][0]['status'] == 'STALE'
    failed = Engine(tmp_path).verify(trusted=True)
    assert not failed['gate'] and failed['executed'] == ['power.budget']
    assert failed['requirements'][0]['comparisons'][0]['margin'] == -20
