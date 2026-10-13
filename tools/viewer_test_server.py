"""Disposable real server for browser tests; never edits the source example."""
import json
import shutil
import tempfile
from pathlib import Path

from closure.engine import approve_baseline
from closure.project import Project
from closure.viewer_server import create_server

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='closure-browser-') as scratch:
    project = Path(scratch)/'service'
    shutil.copytree(ROOT/'examples/service', project,
                    ignore=shutil.ignore_patterns('.closure', '__pycache__', 'deliverables', 'reviews'))
    approve_baseline(Project(project), 'Browser fixture', 'Synthetic service example')
    server = create_server(project, port=0, workspace=scratch, trusted=True)
    print(json.dumps({'url':f'http://127.0.0.1:{server.server_port}'}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
