"""Read-only release checks. --publication additionally requires owner sign-off."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from closure import __version__
from closure.schemas import schemas
from closure.viewer_server import VIEWER_API

ROOT = Path(__file__).resolve().parents[1]


def publication_errors(metadata, record):
    errors = []
    for key in ('copyright_owner', 'website_url', 'repository_url', 'security_contact'):
        if not metadata.get(key): errors.append(f'Owner review required: {key}')
    for key in ('license_and_ownership', 'public_contents', 'publish'):
        if metadata.get('approvals', {}).get(key) is not True:
            errors.append(f'Approval pending: {key}')
    onboarding = metadata.get('onboarding', {})
    if onboarding.get('status') not in ('complete', 'deferred_to_preview') or not onboarding.get('reason'):
        errors.append('Onboarding must be completed or explicitly deferred with a reason')
    if not record:
        return errors + ['Final release record required: --release-record PATH']
    commit = record.get('source_commit', '')
    ci = record.get('ci', {})
    if not re.fullmatch(r'[0-9a-f]{40}', commit): errors.append('Release source_commit must be a full Git SHA')
    if record.get('implementation_version') != metadata['implementation_version']:
        errors.append('Release record version differs')
    if ci.get('conclusion') != 'success' or ci.get('source_commit') != commit:
        errors.append('Successful CI required for the exact release commit')
    if not re.fullmatch(re.escape(metadata['repository_url']) + r'/actions/runs/[0-9]+', ci.get('run_url', '')):
        errors.append('Release CI run URL required')
    return errors


def check(publication=False, release_record=None):
    errors=[]
    metadata=json.loads((ROOT/'release/preview.json').read_text(encoding='utf-8'))
    frontend=json.loads((ROOT/'frontend/package.json').read_text())
    lock=json.loads((ROOT/'frontend/package-lock.json').read_text())
    if metadata['implementation_version'] != __version__: errors.append('Implementation version differs from release manifest')
    if f'version = "{__version__}"' not in (ROOT/'pyproject.toml').read_text(): errors.append('Python metadata version differs')
    if frontend['version'] != metadata['viewer_version'] or lock['version'] != frontend['version']: errors.append('Viewer versions differ')
    if VIEWER_API != metadata['viewer_api']: errors.append('Viewer API version differs')
    for name,schema in schemas().items():
        if json.loads((ROOT/'schema'/f'{name}.schema.json').read_text()) != schema: errors.append(f'Schema drift: {name}')
    for path in ('LICENSE','NOTICE','THIRD_PARTY_NOTICES.md','README.md','CHANGELOG.md','SECURITY.md','CONTRIBUTING.md','spec/0.1/SPECIFICATION.md','docs/QUICKSTART.md'):
        if not (ROOT/path).is_file(): errors.append(f'Missing release file: {path}')
    if hashlib.sha256((ROOT/'LICENSE').read_bytes()).hexdigest() != 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30': errors.append('Official Apache license text changed')
    protected={'Closure_RFC_0001.md':'721904a15ab605dbaeb5ba0c00be5cb4972baf9338e50935d9cce8f2ede29a5e','MTP.md':'d8c4969c5f1f1e486e0787514821a705a305152af920c535ea3409ce82710b07','NORTH_STAR.md':'dfddd44194f7861e268660f608b14ed4f078791640033443115242fea182c4c4'}
    for path,expected in protected.items():
        if (ROOT/path).exists() and hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=expected: errors.append(f'Protected source changed: {path}')
    if publication:
        errors.extend(publication_errors(metadata, release_record))
        for path in ('NOTICE','SECURITY.md'):
            if re.search('placeholder|pending release|not yet assigned', (ROOT/path).read_text(), re.I): errors.append(f'Unfinished publication text: {path}')
    return errors


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication',action='store_true')
    parser.add_argument('--release-record', type=Path, help='Final provenance record kept outside the committed source tree')
    args=parser.parse_args()
    record=json.loads(args.release_record.read_text(encoding='utf-8')) if args.release_record else None
    errors=check(args.publication, record)
    print(json.dumps({'mode':'publication' if args.publication else 'review','passed':not errors,'errors':errors},indent=2))
    raise SystemExit(bool(errors))
