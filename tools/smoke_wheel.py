"""Install a local wheel into a new target and exercise its bundled starter.

Uses the invoking interpreter's dependencies; this is a package-content smoke
check, not a claim of clean-machine dependency or external-tool installation.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import uuid
import venv
from datetime import datetime, timezone
from pathlib import Path


CHECK = r'''
import contextlib, io, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import closure
from closure.cli import main
from closure.engine import Engine, approve_baseline
from closure.project import Project
from closure.reporting import export_report
package = Path(closure.__file__).resolve().parent
assert package.is_relative_to(Path(sys.argv[1]).resolve())
assert (package/'viewer/app.js').stat().st_size > 1000
assert (package/'viewer/style.css').is_file()
for template in ('minimal','power'):
    assert (package/'templates'/template/'project.yaml').is_file()
root = Path(sys.argv[2])
with contextlib.redirect_stdout(io.StringIO()):
    assert main(['init','--project',str(root)]) == 0
project = Project(root)
assert project.check()['valid']
assert not Engine(project).build(trusted=True)['gate']
approve_baseline(project,'Package smoke check','Review the unchanged disposable starter fixture')
report = Engine(root).build(trusted=True)
assert report['gate']
assert Engine(root).plan()['gate']
export_report(root,root/'report')
assert (root/'report/index.html').is_file()
with contextlib.redirect_stdout(io.StringIO()):
    assert main(['schema','--output',str(root/'schema')]) == 0
    assert main(['help','verify']) == 0
    assert main(['completion','powershell']) == 0
    assert main(['completion','bash']) == 0
    assert main(['set','system.allocation','0.6','--project',str(root)]) == 0
assert Project(root).parameters['system.allocation'].value == 0.6
structured = io.StringIO()
with contextlib.redirect_stdout(structured), contextlib.redirect_stderr(io.StringIO()) as errors:
    assert main(['verify','--project',str(root),'--trusted','--json']) == 0
assert not errors.getvalue()
cli_report = json.loads(structured.getvalue())
assert cli_report['gate'] and cli_report['executed'] == ['system.evaluate']
assert (root/'schema/runner-response.schema.json').is_file()
assert (root/'schema/report.schema.json').is_file()
print(json.dumps({'package':str(package),'project':report['project'],'gate':report['gate'],
                  'analyses':len(report['analyses']),'report':report['id'],
                  'checks':['bundled viewer','both templates','init','check','build',
                            'baseline review','plan','portable export','runtime schemas',
                            'CLI help','completion scripts','CLI set','CLI verify JSON']}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--isolated', action='store_true', help='Resolve dependencies in a fresh virtual environment')
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    scratch = Path.cwd()/'.closure'/('package-smoke-'+uuid.uuid4().hex)
    scratch.mkdir(parents=True)
    interpreter = Path(sys.executable)
    if args.isolated:
        environment = scratch/'venv'
        # pip --python also works on Linux distributions without ensurepip.
        # The new interpreter still has no access to the invoking environment.
        venv.EnvBuilder(with_pip=False).create(environment)
        interpreter = environment/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        subprocess.run([sys.executable,'-m','pip','--python',str(interpreter),'install','pip',str(wheel)],check=True,stdout=subprocess.PIPE,text=True)
        target = Path(subprocess.check_output([str(interpreter),'-c','import sysconfig; print(sysconfig.get_paths()["purelib"])'],text=True).strip())
    else:
        target = scratch/'installed'
        subprocess.run([str(interpreter),'-m','pip','install','--no-index','--no-deps',
                        '--target',str(target),str(wheel)],check=True,stdout=subprocess.PIPE,text=True)
    result = subprocess.run([str(interpreter),'-c',CHECK,str(target),str(scratch/'project')],
                            check=True,capture_output=True,text=True,encoding='utf-8')
    checked=json.loads(result.stdout)
    if args.isolated:
        command=interpreter.parent/('closure.exe' if sys.platform=='win32' else 'closure')
        assert subprocess.check_output([str(command),'--version'],text=True).strip()=='closure 0.1.0a1'
        state=json.loads(subprocess.check_output([str(command),'check','-p',str(scratch/'project'),'--json'],text=True))
        assert state['valid']
        checked['checks'].append('installed console entrypoint')
    evidence = {'at':datetime.now(timezone.utc).isoformat(),'wheel':wheel.name,
                'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),
                'python':sys.version,'result':checked,
                'environment':'fresh virtual environment with resolved dependencies' if args.isolated else 'fresh target with existing interpreter dependencies',
                'dependencies':json.loads(subprocess.check_output([str(interpreter),'-m','pip','list','--format=json'],text=True)) if args.isolated else None}
    text = json.dumps(evidence,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text,encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
