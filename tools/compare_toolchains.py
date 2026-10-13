"""Reproduce the RFC power regression in Closure and Doorstop + DVC.

Run with Python from an environment containing Doorstop and DVC, and supply a
separate Closure interpreter. Only disposable local repositories are modified.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import yaml


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--closure-python',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    work=Path(tempfile.mkdtemp(prefix='closure-tool-comparison-'))
    existing=work/'existing'; closure=work/'closure'
    shutil.copytree(repo/'examples/comparison/existing_tools',existing)
    shutil.copytree(repo/'examples/power',closure,ignore=shutil.ignore_patterns('.closure','deliverables','__pycache__'))
    env={**os.environ,'PATH':str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH',''),
         'DVC_NO_ANALYTICS':'true','DVC_STUDIO_OFFLINE':'true','CI':'true','PYTHONIOENCODING':'utf-8'}
    commands=[]
    def run(label,argv,cwd=existing,expected=0):
        result=subprocess.run(list(map(str,argv)),cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
        commands.append({'label':label,'command':list(map(str,argv)),'returncode':result.returncode,
                         'stdout':result.stdout[:8000],'stderr':result.stderr[:8000]})
        if expected is not None:
            assert result.returncode==expected,(label,result.returncode,result.stdout,result.stderr)
        return result
    dvc=lambda *tail:[sys.executable,'-m','dvc',*tail]
    doorstop=lambda *tail:[str(Path(sys.executable).parent/'doorstop'),*tail]
    closure_cli=lambda *tail:[args.closure_python,'-m','closure',*tail,'--project',closure,'--json']
    def claim(result):
        report=json.loads(result.stdout)
        return {'gate':report['gate'],'executed':report['executed'],'assessment':report['requirements'][0]}
    def metrics():
        return json.loads((existing/'metrics.json').read_text(encoding='utf-8'))
    def payload(value):
        (existing/'params.json').write_text(json.dumps({'payload_w':value,'base_w':100})+'\n',encoding='utf-8')

    run('local Git setup',['git','init','--initial-branch=main'])
    run('fixture author',['git','config','user.name','Closure comparison fixture'])
    run('fixture email',['git','config','user.email','fixture@localhost.invalid'])
    run('local DVC setup',dvc('init','--quiet'))
    run('disable update checks',dvc('config','core.check_update','false'))
    run('DVC baseline',dvc('repro'))
    assert metrics()['total_w']==180 and metrics()['criterion_passed']
    reference={'baseline':metrics()}
    reference['baseline_status']=json.loads(run('DVC baseline status',dvc('status','--json')).stdout)
    assert reference['baseline_status']=={}
    run('baseline numerical gate',[sys.executable,'gate.py'])
    run('Doorstop baseline review',doorstop('review','all'))
    run('Doorstop baseline validation',doorstop())
    run('stage baseline',['git','add','.'])
    run('commit fixture baseline',['git','commit','-m','Reviewed power fixture baseline'])
    reference['reviewed_item']=yaml.safe_load((existing/'requirements/PWR001.yml').read_text(encoding='utf-8'))

    payload(120)
    reference['stale_status']=json.loads(run('DVC changed input status',dvc('status','--json')).stdout)
    assert reference['stale_status']
    run('stale numerical gate',[sys.executable,'gate.py'],expected=2)
    review_result=run('Doorstop changed reference validation',doorstop(),expected=None)
    reference['changed_reference_validation']={'returncode':review_result.returncode,'output':review_result.stdout+review_result.stderr}
    run('DVC rebuild',dvc('repro'))
    reference['rebuilt']=metrics()
    assert metrics()['total_w']==220 and metrics()['margin_w']==-20 and not metrics()['criterion_passed']
    run('failing numerical gate',[sys.executable,'gate.py'],expected=1)
    reference['metrics_diff']=json.loads(run('DVC metric explanation',dvc('metrics','diff','--json')).stdout)
    payload(80)
    run('DVC restore baseline',dvc('repro'))
    assert metrics()['total_w']==180
    run('restored numerical gate',[sys.executable,'gate.py'])
    reference['restored']=metrics()
    reference['dvc_lock']=yaml.safe_load((existing/'dvc.lock').read_text(encoding='utf-8'))

    comparison={'baseline':claim(run('Closure baseline',closure_cli('build','--trusted'),cwd=closure))}
    baseline=json.loads(run('Closure source identity',closure_cli('plan'),cwd=closure).stdout)
    run('Closure change payload',closure_cli('patch','--expected-hash',baseline['source_hash'],
        '--changes',json.dumps({'payload.peak_power':{'value':120,'unit':'W'}})),cwd=closure)
    comparison['stale']=claim(run('Closure changed input plan',closure_cli('plan'),cwd=closure))
    assert comparison['stale']['assessment']['status']=='STALE'
    comparison['rebuilt']=claim(run('Closure rebuild',closure_cli('build','--trusted'),cwd=closure,expected=1))
    assert comparison['rebuilt']['assessment']['comparisons'][0]['actual']==220
    comparison['explanation']=json.loads(run('Closure explanation',closure_cli('explain','power.PWR-001'),cwd=closure).stdout)
    latest=json.loads(run('Closure changed source identity',closure_cli('plan'),cwd=closure).stdout)
    run('Closure restore payload',closure_cli('patch','--expected-hash',latest['source_hash'],
        '--changes',json.dumps({'payload.peak_power':{'value':80,'unit':'W'}})),cwd=closure)
    comparison['restored']=claim(run('Closure restored build',closure_cli('build','--trusted'),cwd=closure))
    assert comparison['restored']['gate'] and not comparison['restored']['executed']
    result={'at':datetime.now(timezone.utc).isoformat(),'versions':{p:importlib.metadata.version(p) for p in ['dvc','doorstop']},
            'existing_tools':reference,'closure':comparison,'commands':commands,
            'limitations':['Self-authored functional comparison, not observed user onboarding or a performance benchmark.',
                           'No cloud services or remote repositories are used.','The numerical gate is authored glue, distinct from DVC execution success or Doorstop review.']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(args.output),'versions':result['versions'],
                      'existing_tools':[reference['baseline']['total_w'],reference['rebuilt']['total_w'],reference['restored']['total_w']],
                      'closure':[comparison[k]['assessment']['status'] for k in ['baseline','stale','rebuilt','restored']]}))


if __name__=='__main__':
    main()
