"""Create an allowlisted source review archive. Never uploads or publishes."""
import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FILES=['README.md','pyproject.toml','MANIFEST.in','LICENSE','NOTICE','THIRD_PARTY_NOTICES.md','CHANGELOG.md','CONTRIBUTING.md','SECURITY.md','.gitignore','.gitattributes']
TREES=['src','schema','spec','conformance','tests','tools','frontend','examples','.github']
DOCS=['AUTHORING_STANDARD.md','CLI_GUIDE.md','ENGINE_GUIDE.md','VIEWER_GUIDE.md','VIEWER_API.md','QUICKSTART.md','COMPATIBILITY.md','RELEASE.md','PEN_INPUT_AUDIT.md']
OMIT={'.closure','node_modules','__pycache__','.pytest_cache','.hypothesis','deliverables','baseline-history','test-results','playwright-report'}


def candidates():
    paths=[ROOT/p for p in FILES]
    for tree in TREES:
        for path in (ROOT/tree).rglob('*'):
            relative=path.relative_to(ROOT)
            if path.is_file() and not path.is_symlink() and not (set(relative.parts)&OMIT) and not any(p.endswith('.egg-info') for p in relative.parts) and path.name not in ('last-build.json','apply_website_preview.py','prepare_website.py') and path.suffix not in ('.pyc','.pyo'):
                paths.append(path)
    paths += [ROOT/'docs'/name for name in DOCS]
    paths += [ROOT/'release'/name for name in ('preview.json','ONBOARDING_REVIEW.md','dependency-snapshots.json')]
    return sorted(set(paths))


def prepare(output):
    output=output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    source=output/'source'
    entries=[]
    for path in candidates():
        relative=path.relative_to(ROOT)
        destination=source/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,destination)
        entries.append({'path':relative.as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    archive=output/'closure-0.1.0a1-source.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
        for entry in entries:
            info=zipfile.ZipInfo('closure-0.1.0a1/'+entry['path'],date_time=(2026,10,11,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            bundle.writestr(info,(source/entry['path']).read_bytes())
    manifest={'version':'0.1.0a1','status':'review-only; not publication approval','archive':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':entries,
              'excluded':['MTP.md','NORTH_STAR.md','Closure_RFC_0001.md','raw conversation','local evidence stores','development verification logs','prebuilt engineering deliverables','virtual environments','dependency installs','private website configuration']}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(output),'files':len(entries),'archive':str(archive),'sha256':manifest['sha256']},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='New output directory; existing destinations are never overwritten')
    prepare(parser.parse_args().output)
