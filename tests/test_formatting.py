import json
from pathlib import Path

from ruamel.yaml import YAML

from closure.cli import main
from closure.editing import patch_parameters
from closure.engine import Engine
from closure.formatting import format_project, render_source
from closure.io import load_source
from closure.models import Module, Manifest
from closure.project import Project


def test_format_preserves_model_baseline_cache_and_comments(project_dir):
    path = project_dir/'model/payload.yaml'
    text = path.read_text(encoding='utf-8')
    path.write_text('# Keep this design rationale.\n'+text+'\nanalyses: {}\n',encoding='utf-8')
    before = Project(project_dir)
    built = Engine(before).build(trusted=True)
    assert built['gate']
    review = (project_dir/'reviews/baseline.json').read_bytes()
    assert main(['format','--project',str(project_dir)]) == 0
    after = Project(project_dir)
    assert before.manifest == after.manifest and before.modules == after.modules
    assert (project_dir/'reviews/baseline.json').read_bytes() == review
    assert '# Keep this design rationale.' in path.read_text(encoding='utf-8')
    assert Engine(after).verify(trusted=True)['executed'] == []
    assert format_project(project_dir,check=True)['clean']


def test_format_keeps_meaningful_empty_values_and_comments():
    parser=YAML(typ='rt')
    source=parser.load('''schema: closure/0.1
module: example
owner: Tests
parameters:
  message: {value: '', description: ''}
  flag: {value: false}
  count: {value: 0, type: scalar}
  annotated:
    value: 1
    description: '' # Retain this comment beside its field.
analyses:
  run:
    run: {argv: [python, script.py], sources: [script.py]}
    settings: {empty_text: '', zero: 0, flag: false}
    outputs: {result: {unit: W, type: quantity}}
''')
    formatted=render_source(source)
    assert Module.model_validate(parser.load(formatted))==Module.model_validate(source)
    assert 'description: \'\' # Retain' in formatted
    assert "count: {value: 0}" in formatted
    assert 'result: {unit: W}' in formatted
    assert render_source(parser.load(formatted)) == formatted
    manifest=parser.load('schema: closure/0.1\nproject: empty\nscope: []\nscenarios: {}\n')
    assert Manifest.model_validate(parser.load(render_source(manifest)))==Manifest.model_validate(manifest)
    assert 'scope: []' in render_source(manifest)


def test_check_is_read_only_and_edits_use_the_default_style(project_dir):
    path=project_dir/'model/payload.yaml'
    path.write_text(path.read_text(encoding='utf-8')+'\nanalyses: {}\n',encoding='utf-8')
    before=path.read_bytes()
    assert main(['format','--project',str(project_dir),'--check'])==1
    assert path.read_bytes()==before and not (project_dir/'.closure/write.lock').exists()
    patch_parameters(project_dir,Project(project_dir).source_hash,{'payload.peak_power':{'value':120,'unit':'W','type':'quantity'}})
    assert 'analyses: {}' not in path.read_text(encoding='utf-8')
    assert 'type: quantity' not in path.read_text(encoding='utf-8')
    assert render_source(load_source(path))==path.read_text(encoding='utf-8')
    assert format_project(project_dir,check=True)['clean']


def test_json_stays_json_and_report_files_are_not_formatted(project_dir):
    path=project_dir/'model/payload.yaml'
    data=load_source(path)
    data['description']=''
    path.with_suffix('.json').write_text(json.dumps(data),encoding='utf-8')
    path.unlink()
    manifest=project_dir/'project.yaml'
    manifest.write_text(manifest.read_text(encoding='utf-8').replace('model/*.yaml','model/*.*'),encoding='utf-8')
    retained=project_dir/'deliverables/fixture.yaml'
    retained.parent.mkdir(); retained.write_text('unrelated: {}\n',encoding='utf-8')
    format_project(project_dir)
    assert json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))['module']=='payload'
    assert retained.read_text()=='unrelated: {}\n'
    assert format_project(project_dir,check=True)['clean']
