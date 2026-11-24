"""Disposable real server for browser tests; never edits the source example."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

from closure.engine import Engine, approve_baseline, record_review
from closure.project import Project
from closure.viewer_server import create_server

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--invalid-current", action="store_true")
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix='closure-browser-') as scratch:
    project = Path(scratch)/'service'
    shutil.copytree(ROOT/'examples/service', project,
                    ignore=shutil.ignore_patterns('.closure', '__pycache__', 'deliverables', 'reviews'))
    approve_baseline(Project(project), 'Browser fixture', 'Synthetic service example')
    shutil.copytree(ROOT/"examples/composed-power", Path(scratch)/"composed-power",
                    ignore=shutil.ignore_patterns(".closure", "__pycache__"))
    electronics = Path(scratch) / "composed-power" / "electronics"
    Engine(electronics).verify(trusted=True)
    record_review(Engine(electronics), "electronics::load.local_budget", "accepted",
                  "Electronics reviewer", "Checked the component allocation.")
    if args.invalid_current:
        assert Engine(project).verify(trusted=True)["gate"]
        (project / "model/workload.yaml").write_text("parameters: [", encoding="utf-8")
    server = create_server(project, port=0, workspace=scratch, trusted=True)
    print(json.dumps({'url':f'http://127.0.0.1:{server.server_port}'}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
