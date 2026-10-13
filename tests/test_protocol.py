"""Published schemas and runtime validators agree on real exchanges and records."""
import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from closure.cli import main
from closure.engine import Engine, sweep
from closure.evidence import EvidenceStore
from closure.io import ClosureError, atomic_json, canonical, digest
from closure.models import Manifest, Module, Port, Study
from closure.protocol import RUNTIME_SCHEMAS
from closure.units import validate_value
from conftest import edit_yaml, runner


@pytest.mark.parametrize('value,expected', [
    ({'z':-0.0,'a':1,'b':1.0,'é':'雪'}, '{"a":1,"b":1.0,"z":-0.0,"é":"雪"}'),
    ({'truth':True,'nil':None,'lines':'a\nb'}, '{"lines":"a\\nb","nil":null,"truth":true}'),
    ({'small':1e-7}, '{"small":1e-07}'),
])
def test_canonical_01_reference_vectors(value, expected):
    assert canonical(value) == expected.encode('utf-8')


def check_schema(name, value):
    model = RUNTIME_SCHEMAS[name]
    model.model_validate(value)
    schema = json.loads((Path(__file__).parents[1]/'schema'/f'{name}.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate(value)


def test_published_schemas_are_generated_from_compiler_models(tmp_path):
    assert main(['schema','--output',str(tmp_path)]) == 0
    models = {'project': Manifest, 'module': Module, 'study': Study, **RUNTIME_SCHEMAS}
    for name in models:
        generated = json.loads((tmp_path/f'{name}.schema.json').read_text(encoding='utf-8'))
        published = json.loads((Path(__file__).parents[1]/'schema'/f'{name}.schema.json').read_text(encoding='utf-8'))
        assert generated == published
        Draft202012Validator.check_schema(published)


def test_real_request_evidence_plan_build_and_study_match_schemas(project_dir):
    runner(project_dir,
           "p=pathlib.Path(r['output_dir'])/'request.json'\np.write_text(json.dumps(r))\n"
           "json.dump({'protocol':r['protocol'],'invocation_id':r['invocation_id'],'outputs':"
           "{'total':{'value':r['inputs']['payload']['value']+r['inputs']['base']['value'],'unit':'W'},"
           "'request':{'path':str(p),'media_type':'application/json'}}},sys.stdout)",
           {'total':{'type':'quantity','unit':'W'},'request':{'type':'artifact'}})
    check_schema('report', Engine(project_dir).plan())
    report = Engine(project_dir).build(trusted=True)
    assert report['gate']
    check_schema('report', report)
    record = report['analyses'][0]['record']
    check_schema('evidence', record)
    request = json.loads(Path(record['outputs']['request']['path']).read_text(encoding='utf-8'))
    check_schema('runner-request', request)
    check_schema('runner-response', {'protocol':request['protocol'],'invocation_id':request['invocation_id'],
                                   'outputs':{'total':{'value':180,'unit':'W'}}})
    result = sweep(project_dir,'studies/payload_power.yaml',trusted=True)
    assert (result['passed'],result['failed']) == (2,2)
    check_schema('study-result', result)


@pytest.mark.parametrize('field,value', [
    ('converged', 'true'), ('converged', 1), ('residuals', {'residual':True}),
    ('residuals', {'residual':'0.001'}), ('residuals', []), ('unknown_meaning', 'ignore me'),
])
def test_invalid_runner_fields_cannot_publish_evidence(project_dir, field, value):
    runner(project_dir,
           "response={'protocol':r['protocol'],'invocation_id':r['invocation_id'],"
           "'outputs':{'total':{'value':180,'unit':'W'}}}\n"
           f"response[{field!r}]={value!r}\njson.dump(response,sys.stdout)")
    report = Engine(project_dir).build(trusted=True)
    assert not report['gate'] and report['analyses'][0]['error']['code'] == 'OUTPUT_INVALID'
    assert not (project_dir/'.closure/runs').exists()


def test_excessively_nested_runner_json_is_reported_without_crashing(project_dir):
    runner(project_dir, "sys.stdout.write('['*2000+'0'+']'*2000)")
    report = Engine(project_dir).build(trusted=True)
    assert not report['gate']
    assert report['analyses'][0]['error']['code'] == 'OUTPUT_INVALID'
    assert not (project_dir/'.closure/runs').exists()


@pytest.mark.parametrize('envelope', [
    {'path':'shape.glb','type':'scalar'}, {'path':'shape.glb','media_type':42},
    {'path':'shape.glb','sha256':'invented'}, {'path':'shape.glb','name':False},
    {'path':'shape.glb','value':1},
])
def test_artifact_envelopes_reject_incompatible_types_and_metadata(envelope):
    with pytest.raises(ClosureError) as failure:
        validate_value(envelope, Port(type='artifact'))
    assert failure.value.code == 'OUTPUT_INVALID'


def test_artifact_qualifiers_survive_inputs_records_and_reuse(project_dir):
    (project_dir/'source.step').write_text('opaque geometry',encoding='utf-8')
    edit_yaml(project_dir/'model/payload.yaml', lambda d: (
        d['parameters'].update(shape={'type':'artifact','path':'source.step','qualifiers':{'frame':'body'}}),
        d['exports'].append('shape')))
    edit_yaml(project_dir/'model/power.yaml', lambda d: d['analyses']['budget']['inputs'].update(
        shape={'ref':'payload.shape','qualifiers':{'frame':'body'}}))
    runner(project_dir,
           "assert r['inputs']['shape']['qualifiers']=={'frame':'body'}\n"
           "json.dump({'protocol':r['protocol'],'invocation_id':r['invocation_id'],'outputs':"
           "{'total':{'value':180,'unit':'W'},'shape':{'path':r['inputs']['shape']['path'],"
           "'qualifiers':{'frame':'body'}}}},sys.stdout)",
           {'total':{'type':'quantity','unit':'W'},'shape':{'type':'artifact','qualifiers':{'frame':'body'}}})
    report = Engine(project_dir).build(trusted=True)
    assert report['gate'] and report['values']['power.budget.shape']['qualifiers'] == {'frame':'body'}
    assert Engine(project_dir).build(trusted=True)['executed'] == []
    with pytest.raises(ClosureError) as failure:
        validate_value({'path':'shape.step','qualifiers':{'frame':'world'}}, Port(type='artifact',qualifiers={'frame':'body'}))
    assert failure.value.code == 'QUALIFIER_MISMATCH'


def test_structurally_invalid_history_is_rejected_even_with_matching_digest(project_dir):
    report = Engine(project_dir).build(trusted=True)
    record = copy.deepcopy(report['analyses'][0]['record'])
    record['outputs']['total']['value'] = True
    record.pop('record_hash')
    record['record_hash'] = digest(record)
    store = EvidenceStore(project_dir)
    atomic_json(store.root/'runs'/f"{record['id']}.json",record)
    with pytest.raises(ClosureError) as failure:
        store.load_run(record['id'])
    assert failure.value.code == 'HISTORY_CORRUPT'
    report['gate'] = 1  # JSON number must not be silently coerced into a boolean.
    report.pop('report_hash')
    report['report_hash'] = digest(report)
    atomic_json(store.root/'reports'/f"{report['id']}.json",report)
    with pytest.raises(ClosureError) as failure:
        store.load_report(report['id'])
    assert failure.value.code == 'HISTORY_CORRUPT'
