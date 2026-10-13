"""Existing orbit propagator crosses team boundaries through ordinary runners."""
import csv
import math
from pathlib import Path
import shutil

import pytest

pytest.importorskip('sgp4', reason='Install the mission extra for the SGP4 example')
from closure.editing import patch_parameters
from closure.engine import Engine, approve_baseline, sweep
from closure.project import Project
from closure.reporting import export_report


def test_orbit_energy_change_and_sampled_study(tmp_path):
    shutil.copytree(Path(__file__).parents[1]/'examples/mission', tmp_path,
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns('.closure','deliverables','__pycache__'))
    approve_baseline(Project(tmp_path), 'test reviewer', 'Review the synthetic mission fixture')
    baseline = Engine(tmp_path).build(trusted=True)
    assert baseline['gate'], [(a['id'], a.get('error')) for a in baseline['analyses']]
    values = baseline['values']
    # Independent circular-orbit geometry is a coarse check on the real propagator.
    period = 86400 / 15.2
    semimajor = (398600.8 * (period/(2*math.pi))**2)**(1/3)
    analytic_eclipse = period / math.pi * math.asin(6378.135/semimajor)
    eclipse = values['orbit.propagate.max_eclipse']['value']
    assert abs(eclipse-analytic_eclipse) < 120
    assert 400 < values['orbit.propagate.min_altitude']['value'] < 650
    assert 17 < values['power.energy.demand']['value'] < 20
    assert 50 < values['power.energy.reserve']['value'] < 60
    artifact = values['orbit.propagate.trajectory']
    assert artifact['qualifiers'] == {'frame':'TEME'}
    with Path(artifact['path']).open(encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 721 and float(rows[-1]['seconds_since_2026_10_11_UTC']) == 21600
    assert {row['shadow'] for row in rows} == {'0','1'}

    patch_parameters(tmp_path, Project(tmp_path).source_hash, {'payload.draw':{'value':70,'unit':'W'}})
    states = {a['id']:a['state'] for a in Engine(tmp_path).plan()['analyses']}
    assert states == {'orbit.propagate':'current', 'power.energy':'stale'}
    failed = Engine(tmp_path).build(trusted=True)
    assert not failed['gate'] and failed['executed'] == ['power.energy']
    assert failed['values']['power.energy.reserve']['value'] < 0
    explanation = Engine(tmp_path).explain('operations.ENE-001')
    assert any(p[0] == 'payload.draw' and 'power.energy' in p for p in explanation['paths'])
    assert Engine(tmp_path, 'high_load', 'extended').build(trusted=True)['gate']
    patch_parameters(tmp_path, Project(tmp_path).source_hash, {'payload.draw':{'value':20,'unit':'W'}})
    assert Engine(tmp_path).build(trusted=True)['executed'] == []

    patch_parameters(tmp_path, Project(tmp_path).source_hash, {'orbit.mean_motion':{'value':15,'unit':'1/day'}})
    assert all(a['state'] != 'current' for a in Engine(tmp_path).plan()['analyses'])
    changed = Engine(tmp_path).build(trusted=True)
    assert changed['executed'] == ['orbit.propagate','power.energy'] and changed['gate']
    assert changed['values']['orbit.propagate.min_altitude']['value'] > values['orbit.propagate.min_altitude']['value'] + 40
    patch_parameters(tmp_path, Project(tmp_path).source_hash, {'orbit.mean_motion':{'value':15.2,'unit':'1/day'}})
    study = sweep(tmp_path, tmp_path/'studies/energy.yaml', trusted=True)
    assert study['complete_evidence'] and study['completed'] == study['expected'] == 6
    assert study['passed'] == 5 and study['failed'] == 1
    assert export_report(tmp_path, tmp_path/'deliverables/test', report_id=baseline['id'])
