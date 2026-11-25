"""Check a wheel's bundled starter and, with --isolated, verify a composed project using its installed CLI."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import venv
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]

CHECK = r'''
import contextlib, io, json, sys
from pathlib import Path
from sysconfig import get_path
if sys.argv[1]:
    sys.path.insert(0, sys.argv[1])
import closure
from closure.cli import main
from closure.engine import Engine, approve_baseline
from closure.project import Project
from closure.reporting import export_report
package = Path(closure.__file__).resolve().parent
assert package.is_relative_to(Path(sys.argv[1] or get_path('purelib')).resolve())
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


def check_composition(command, scratch, env):
    project = scratch / 'composed-power'
    shutil.copytree(SOURCE / 'examples' / 'composed-power', project,
                    ignore=shutil.ignore_patterns('.closure', '__pycache__'))

    def cli(*args, expected_exit=0):
        result = subprocess.run([command, *args, '--json'], cwd=project, env=env,
                                capture_output=True, encoding='utf-8')
        if result.returncode != expected_exit:
            raise RuntimeError(f"closure {args[0]} exited {result.returncode}, expected {expected_exit}\n"
                               f"{result.stderr or result.stdout}")
        return json.loads(result.stdout)

    requirement_id = 'system::budget.power'

    def check_budget(report, limit, passed):
        requirement = next(row for row in report['requirements'] if row['id'] == requirement_id)
        comparison, = requirement['comparisons']
        children = {name: report['gates'][name]['gate'] for name in ('electronics', 'cooling')}
        assert report['schema'] == 'closure-report/0.2'
        assert report['gate'] is passed and report['gates']['system']['gate'] is passed
        assert all(children.values()), children
        assert requirement['status'] == ('PASS' if passed else 'FAIL'), requirement['status']
        assert (comparison['actual'], comparison['limit'], comparison['unit']) == (104, limit, 'W'), comparison
        return {'report': report['id'], 'report_hash': report['report_hash'], 'gate': report['gate'], 'children': children,
                'actual': comparison['actual'], 'limit': comparison['limit'], 'unit': comparison['unit'],
                'executed': report['executed']}

    first = cli('verify', '--trusted')
    passing = check_budget(first, 110, True)
    assert sorted(first['executed']) == ['cooling::load.scale', 'electronics::load.scale',
                                         'reference::profile.evaluate', 'system::budget.sum'], first['executed']

    cli('set', 'system::budget.maximum', '100')
    second = cli('verify', '--trusted', expected_exit=1)
    tightened = check_budget(second, 100, False)
    assert second['executed'] == [], second['executed']
    first_runs = {a['id']: a['record']['id'] for a in first['analyses']}
    assert first_runs.keys() == set(first['executed'])
    assert {a['id']: a['record']['id'] for a in second['analyses']} == first_runs

    destination = scratch / 'passing-report'
    export = cli('export', '--report', first['id'], '--output', destination)
    assert export['mode'] == 'historical' and (destination / 'index.html').is_file()
    assert (export['report'], export['report_hash']) == (first['id'], first['report_hash'])
    assert json.loads((destination / 'report.json').read_bytes()) == first
    return {'command': str(command), 'working_directory': str(project), 'requirement': requirement_id,
            'passing': passing, 'tightened': tightened,
            'exported_report': export['report'], 'exported_hash': export['report_hash']}


def smoke_wheel(wheel, scratch, isolated):
    interpreter = Path(sys.executable)
    env = os.environ.copy()
    dependencies = None
    if isolated:
        for key in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONOPTIMIZE'):
            env.pop(key, None)
        env['PYTHONIOENCODING'] = 'utf-8'
        environment = scratch/'venv'
        # pip --python also works on Linux distributions without ensurepip.
        # The new interpreter still has no access to the invoking environment.
        venv.EnvBuilder(with_pip=False).create(environment)
        interpreter = environment/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        env['VIRTUAL_ENV'] = str(environment)
        env['PATH'] = str(interpreter.parent) + os.pathsep + env.get('PATH', '')
        subprocess.run([sys.executable,'-m','pip','--python',str(interpreter),'install','pip',str(wheel)],
                       cwd=scratch, env=env, check=True, stdout=sys.stderr)
        target = ''
    else:
        target = scratch/'installed'
        subprocess.run([str(interpreter),'-m','pip','install','--no-index','--no-deps',
                        '--target',str(target),str(wheel)],check=True,stdout=subprocess.PIPE,text=True)
    result = subprocess.run([interpreter, '-c', CHECK, str(target), str(scratch / 'project')],
                            cwd=scratch if isolated else None, env=env, check=True, stdout=subprocess.PIPE, encoding='utf-8')
    checked = json.loads(result.stdout)
    if isolated:
        command = interpreter.parent / ('closure.exe' if sys.platform == 'win32' else 'closure')
        version = subprocess.check_output([command, '--version'], cwd=scratch, env=env, text=True)
        assert version.strip() == 'closure 0.2.0a1'
        state = json.loads(subprocess.check_output([command, 'check', '-p', scratch / 'project', '--json'], cwd=scratch, env=env))
        assert state['valid']
        checked['checks'].append('installed console entrypoint')
        checked['composition'] = check_composition(command, scratch, env)
        checked['checks'].append('installed composed verification, reuse and historical export')
        dependencies = json.loads(subprocess.check_output([interpreter, '-m', 'pip', 'list', '--format=json'], cwd=scratch, env=env))
    return {'at': datetime.now(timezone.utc).isoformat(), 'wheel': wheel.name,
            'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(), 'python': sys.version, 'result': checked,
            'environment': 'fresh virtual environment with resolved dependencies' if isolated else 'fresh target with existing interpreter dependencies',
            'dependencies': dependencies}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--isolated', action='store_true', help='Resolve dependencies in a fresh virtual environment')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Wheel smoke checks require Python assertions to be enabled.')
    wheel = args.wheel.resolve(strict=True)
    if args.isolated:
        checkout = next((p for p in (SOURCE, *SOURCE.parents) if (p / '.git').exists()), SOURCE)
        temp_root = Path(tempfile.gettempdir()).resolve()
        if temp_root.is_relative_to(checkout):
            temp_root = checkout.parent
        with tempfile.TemporaryDirectory(prefix='closure-wheel-', dir=temp_root) as directory:
            evidence = smoke_wheel(wheel, Path(directory), True)
    else:
        scratch = Path.cwd()/'.closure'/('package-smoke-'+uuid.uuid4().hex)
        scratch.mkdir(parents=True)
        evidence = smoke_wheel(wheel, scratch, False)
    text = json.dumps(evidence,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text,encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
