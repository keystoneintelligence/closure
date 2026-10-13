import pytest

from closure.cli import main
from closure.engine import Engine
from closure.io import ClosureError


def test_verify_reuses_current_evidence_or_forces_a_fresh_run(project_dir):
    baseline=Engine(project_dir).verify(trusted=True)
    assert baseline['gate']
    assert Engine(project_dir).verify(trusted=True)['executed']==[]
    forced=Engine(project_dir).verify(trusted=True,force=True)
    assert forced['gate'] and forced['executed']==['power.budget']
    assert forced['analyses'][0]['record']['id']!=baseline['analyses'][0]['record']['id']
    assert main(['verify','--project',str(project_dir),'--trusted','--force'])==0
    with pytest.raises(ClosureError,match='trusted'):
        Engine(project_dir).verify(force=True)


def test_failed_forced_run_does_not_report_old_passing_values(project_dir, monkeypatch):
    assert Engine(project_dir).verify(trusted=True)['gate']
    engine=Engine(project_dir)
    def failure(*args,**kwargs):
        raise ClosureError('Injected solver failure','RUN_ERROR')
    monkeypatch.setattr(engine.store,'execute',failure)
    result=engine.verify(trusted=True,force=True)
    assert not result['gate'] and result['requirements'][0]['execution']=='error'
    assert 'power.budget.total' not in result['values']
    assert result['analyses'][0]['record'] is None
    planned=Engine(project_dir).plan()
    assert not planned['gate'] and planned['analyses'][0]['state']=='stale'
    assert Engine(project_dir).verify(trusted=True)['executed']==['power.budget']
