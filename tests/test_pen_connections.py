"""Cheap input-propagation checks complement the actual CAD integration suite."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from closure.evidence import source_snapshot
from closure.project import Project

ROOT = Path(__file__).parents[1]/'examples/pen'


def run_analysis(tmp_path, identifier, overrides=None, upstream=None):
    project=Project(ROOT)
    analysis=project.analyses[identifier]
    inputs={}
    for name,binding in analysis.inputs.items():
        if binding.ref in project.parameters:
            datum=project.parameters[binding.ref]
            inputs[name]={'value':datum.value, 'unit':binding.unit or datum.unit}
        else:
            inputs[name]=upstream[binding.ref]
    inputs.update(overrides or {})
    output=tmp_path/identifier
    output.mkdir(exist_ok=True)
    request={'protocol':'closure-run/0.1','invocation_id':'test','inputs':inputs,
             'settings':analysis.settings,'output_dir':str(output)}
    process=subprocess.run([sys.executable,str(ROOT/analysis.run.argv[1])],
        input=json.dumps(request),capture_output=True,text=True,encoding='utf-8',check=True)
    return json.loads(process.stdout)['outputs']


def test_crown_width_drives_both_cad_and_the_force_screen(tmp_path):
    p=Project(ROOT)
    paths=p.impact('mechanism.crown_width')['affected']
    assert 'manufacturing.cad' in paths and 'mechanism.kinematics' in paths
    normal=run_analysis(tmp_path,'mechanism.motion')
    wider=run_analysis(tmp_path,'mechanism.motion',{'crown_width':{'value':1.6,'unit':'mm'}})
    assert wider['minimum_crown_slope']['value'] < normal['minimum_crown_slope']['value']
    radius=p.parameters['mechanism.cam_radius'].value
    assert wider['minimum_crown_slope']['value']/normal['minimum_crown_slope']['value'] == pytest.approx((radius+1.4/2)/(radius+1.6/2))


def test_spring_end_turns_affect_screening_and_reach_cad(tmp_path):
    p=Project(ROOT)
    assert {'spring.response','manufacturing.cad'} <= set(p.impact('spring.inactive_coils')['affected'])
    upstream={'mechanism.motion.max_rotor_stroke':{'value':4.95,'unit':'mm'}}
    normal=run_analysis(tmp_path,'spring.response',upstream=upstream)
    changed=run_analysis(tmp_path,'spring.response',{'inactive_coils':{'value':4}},upstream)
    assert changed['solid_height']['value']-normal['solid_height']['value'] == pytest.approx(1.05*2*(.45+.01))
    assert changed['solid_clearance']['value'] < normal['solid_clearance']['value']
    assert changed['rate']['value'] == normal['rate']['value']


def test_animation_period_is_consumed_from_the_motion_artifact():
    spec=importlib.util.spec_from_file_location('pen_animation',ROOT/'analysis/assembly_motion.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    sample={'rotor_mm':0,'rotor_deg':95,'button_mm':0}
    motion={'samples':[sample]*6,'ends':[{'sample_start':i*2,'sample_end':i*2+1} for i in range(3)],'rotational_period_deg':90}
    result=module.animation_metadata(motion,15,5)
    rotation=next(m for m in result['motions'] if m['state']=='returned' and 'rotation_deg' in m)
    assert rotation['rotation_deg'][2] == 5


def test_pen_wrappers_consume_their_declared_inputs():
    # This audit is deliberately scoped to these simple wrappers, not a rule
    # that rejects arbitrary Python programs or tries to prove all dependencies.
    project=Project(ROOT)
    for identifier,analysis in project.analyses.items():
        reads=set()
        for relative in source_snapshot(project,analysis):
            if not relative.endswith('.py'): continue
            for node in ast.walk(ast.parse((ROOT/relative).read_text(encoding='utf-8'))):
                if not isinstance(node,ast.Subscript): continue
                value=node.value
                input_map=(isinstance(value,ast.Name) and value.id in ('v','values')) or (isinstance(value,ast.Attribute) and value.attr=='v')
                if input_map and isinstance(node.slice,ast.Constant) and isinstance(node.slice.value,str): reads.add(node.slice.value)
        assert reads==set(analysis.inputs),(identifier,reads-set(analysis.inputs),set(analysis.inputs)-reads)
