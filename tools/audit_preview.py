"""Verify a prepared source manifest, local links, and known private exclusions."""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path


def audit(folder):
    manifest=json.loads((folder/'manifest.json').read_text())
    source=folder/'source'
    errors=[]
    expected={'closure-0.1.0a1/'+e['path']:e for e in manifest['files']}
    archive=folder/manifest['archive']
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=manifest['sha256']: errors.append('Archive digest differs')
    with zipfile.ZipFile(archive) as bundle:
        if set(bundle.namelist())!=set(expected): errors.append('Archive contents differ from manifest')
        for name,entry in expected.items():
            payload=bundle.read(name)
            if hashlib.sha256(payload).hexdigest()!=entry['sha256']: errors.append('Content digest differs: '+name)
            if payload!=(source/entry['path']).read_bytes(): errors.append('Review source differs: '+name)
            parts=Path(entry['path']).parts
            if set(parts)&{'MTP.md','NORTH_STAR.md','Closure_RFC_0001.md','Closure_Conversation_Context.txt'}: errors.append('Private source document: '+name)
            if set(parts)&{'.closure','node_modules','.venv','deliverables','verification'}: errors.append('Private/development path: '+name)
            if entry['path'].endswith('Closure_Conversation_Context.txt'):
                if not payload.startswith(b'The supplied historical conversation is retained privately'): errors.append('Historical conversation exposed')
                continue
            try: content=payload.decode('utf-8')
            except UnicodeDecodeError: continue
            if re.search(r'(?:[CEF]:[/\\](?:Users|data|Programs)|/mnt/[cef]/|C:\\Users\\)',content): errors.append('Machine-specific path: '+name)
            if entry['path'].endswith('.md'):
                for target in re.findall(r'\]\(([^)]+)\)',content):
                    target=target.split('#')[0].split(' "')[0]
                    if not target or '://' in target or target.startswith('mailto:'): continue
                    resolved=(source/entry['path']).parent/target
                    if not resolved.exists(): errors.append(f'Broken local link: {entry["path"]} -> {target}')
    return {'passed':not errors,'files':len(expected),'archive_sha256':manifest['sha256'],'errors':errors,
            'scope':'Manifest integrity, local Markdown links, known private paths and development exclusions; not a comprehensive secret or legal audit.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--wheel',type=Path,help='Also compare the exact wheel code/assets to this review source')
    args=parser.parse_args()
    result=audit(args.folder)
    if args.wheel:
        with zipfile.ZipFile(args.wheel) as wheel:
            for name in wheel.namelist():
                if name.startswith('closure/'):
                    source=args.folder/'source/src'/name
                    if not source.is_file() or source.read_bytes()!=wheel.read(name):
                        result['errors'].append('Wheel differs from reviewed code/assets: '+name)
            for notice in ('LICENSE','NOTICE','THIRD_PARTY_NOTICES.md'):
                names=[name for name in wheel.namelist() if name.endswith('/licenses/'+notice)]
                if len(names)!=1 or wheel.read(names[0])!=(args.folder/'source'/notice).read_bytes():
                    result['errors'].append('Wheel license notice mismatch: '+notice)
        result['wheel_sha256']=hashlib.sha256(args.wheel.read_bytes()).hexdigest()
        result['passed']=not result['errors']
    text=json.dumps(result,indent=2)+'\n'
    if args.output: args.output.write_text(text,encoding='utf-8')
    print(text)
    raise SystemExit(not result['passed'])
