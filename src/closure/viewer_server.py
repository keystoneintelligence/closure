"""Loopback-only project explorer, serving the same engine APIs as the CLI."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from .editing import patch_parameters
from .engine import Engine
from .evidence import EvidenceStore
from .io import ClosureError, read_json, within, file_digest
from .project import Project
from .reporting import explain_saved_report
from . import __version__

VIEWER_API = "closure-viewer/0.1"


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR permits two listeners on one port. Exclusive binding
    # avoids nondeterministically serving requests from different engine versions.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        return super().server_bind()


class Viewer:
    def __init__(self, project, workspace=None, trusted=False):
        selected = Project(project)
        self.project = selected.root
        self.manifest_path = selected.manifest_path
        self.workspace = Path(workspace).resolve() if workspace else self.project.parent
        if not self.project.is_relative_to(self.workspace):
            raise ClosureError("Viewer project must be inside its workspace", "PATH_ESCAPE")
        self.trusted = trusted
        self.token = secrets.token_urlsafe(32)

    def projects(self):
        found=[]
        for directory, children, files in os.walk(self.workspace):
            children[:]=[p for p in children if p not in (".closure", ".venv", "node_modules", ".git", "__pycache__")]
            if any(name in files for name in ("project.yaml", "project.yml", "project.json")):
                path=Path(directory)
                try:
                    project=Project(path)
                    found.append({"path":str(path.relative_to(self.workspace)),"name":project.manifest.name or project.manifest.project,"id":project.manifest.project})
                except (ClosureError, ValueError, OSError):
                    continue
        if not any(p["path"] == str(self.project.relative_to(self.workspace)) for p in found):
            selected = Project(self.manifest_path)
            found.append({"path":str(self.project.relative_to(self.workspace)), "name":selected.manifest.name or selected.manifest.project, "id":selected.manifest.project})
        return found

    def engine(self, scenario=None, configuration=None):
        project=Project(self.manifest_path)
        return Engine(project, scenario or next(iter(project.manifest.scenarios), "nominal"),
                      configuration or next(iter(project.manifest.configurations), "default"))

    def snapshot(self, scenario=None, configuration=None, report_id=None):
        report = EvidenceStore(self.project).load_report(report_id) if report_id else self.engine(scenario, configuration).plan()
        return {**report["model"], "path":str(self.project.relative_to(self.workspace)), "report":report,
                "mode":"historical" if report_id else "current", "token":self.token,"trusted":self.trusted,"projects":self.projects()}


def create_server(project, port=8765, workspace=None, trusted=False):
    app=Viewer(project,workspace,trusted)
    operation_lock = threading.RLock()
    static=Path(__file__).parent/"viewer"
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def respond(self, value, status=200):
            payload=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(payload)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Closure-API", VIEWER_API)
            self.send_header("X-Content-Type-Options","nosniff")
            self.end_headers(); self.wfile.write(payload)

        def allowed_host(self):
            return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}")

        def send_file(self,path,media=None,download_name=None):
            if not path.is_file():
                self.respond({"error":"File not found"},404); return
            self.send_response(200)
            self.send_header("Content-Type",media or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length",str(path.stat().st_size))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' blob:; worker-src 'self' blob:; frame-ancestors 'none'")
            if download_name:
                safe=re.sub(r"[^A-Za-z0-9._-]","_",download_name)
                self.send_header("Content-Disposition",f'attachment; filename="{safe}"')
            self.end_headers()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024*1024),b""):
                    self.wfile.write(chunk)

        def do_GET(self):
            if self.path.startswith('/api/'):
                with operation_lock:
                    return self.get_request()
            return self.get_request()

        def get_request(self):
            if not self.allowed_host():
                return self.respond({"error":"Invalid host"},403)
            if self.headers.get('X-Closure-API', VIEWER_API) != VIEWER_API:
                return self.respond({"error":"Viewer API version mismatch; reload the bundled viewer"},409)
            parsed=urlparse(self.path); query=parse_qs(parsed.query)
            try:
                if parsed.path == '/api/version':
                    return self.respond({"api":VIEWER_API,"implementation":__version__,
                                         "source":"closure/0.1","runner":"closure-run/0.1",
                                         "execution":"trusted-local","trusted":app.trusted})
                if parsed.path=="/api/project":
                    return self.respond(app.snapshot(query.get("scenario",[None])[0],query.get("configuration",[None])[0],query.get("report",[None])[0]))
                if parsed.path=="/api/explain":
                    if query.get("report"):
                        return self.respond(explain_saved_report(EvidenceStore(app.project).load_report(query["report"][0]),query.get("id",[""])[0]))
                    return self.respond(app.engine(query.get("scenario",[None])[0],query.get("configuration",[None])[0]).explain(query.get("id",[""])[0]))
                if parsed.path=="/api/history":
                    return self.respond(EvidenceStore(app.project).history())
                if parsed.path=="/api/runs":
                    return self.respond({"mode":"historical", "run":EvidenceStore(app.project).load_run(query.get("id",[""])[0])})
                if parsed.path.startswith("/api/artifacts/"):
                    sha=parsed.path.rsplit("/",1)[-1]
                    if not re.fullmatch("[a-f0-9]{64}",sha): return self.respond({"error":"Invalid artifact"},400)
                    media=query.get("type",[None])[0]
                    allowed_media={"model/gltf-binary","application/json","application/vnd.closure.assembly+json","image/png","image/jpeg","text/plain","text/csv","model/step","application/zip"}
                    if media not in allowed_media: media="application/octet-stream"
                    path=app.project/".closure/artifacts"/sha
                    if path.is_file():
                        path=EvidenceStore(app.project).artifact_path({"sha256":sha})
                    else:
                        for datum in Project(app.manifest_path).parameters.values():
                            if datum.type=="artifact":
                                candidate=within(app.project,datum.path)
                                if candidate.is_file() and file_digest(candidate)==sha:
                                    path=candidate
                                    break
                    return self.send_file(path,media,query.get("download",[None])[0])
                if parsed.path=="/api/source":
                    if query.get("report"):
                        report=EvidenceStore(app.project).load_report(query["report"][0])
                        identifier=query.get("module",[""])[0]
                        module=next((m for m in report["model"]["modules"] if m["module"]==identifier),None)
                        if module is None: return self.respond({"error":"Unknown module in this snapshot"},404)
                        return self.respond({"name":identifier+" — saved normalized contract", "text":json.dumps(module,indent=2)})
                    project=Project(app.manifest_path); identifier=query.get("module",[""])[0]
                    if identifier not in project.modules: return self.respond({"error":"Unknown module"},404)
                    path=Path(project.locations[identifier])
                    return self.respond({"name":path.name,"text":path.read_text(encoding="utf-8")})
                relative=unquote(parsed.path).lstrip("/") or "index.html"
                path=(static/relative).resolve()
                if not path.is_relative_to(static.resolve()): return self.respond({"error":"Invalid path"},403)
                return self.send_file(path)
            except (ClosureError,ValueError,OSError,KeyError) as exc:
                return self.respond({"error":exc.as_dict() if isinstance(exc,ClosureError) else str(exc)},400)

        def do_POST(self):
            # Project selection is session-wide. Keep identity checks and writes
            # together so a second browser tab cannot switch the active project.
            with operation_lock:
                return self.post_request()

        def post_request(self):
            if not self.allowed_host() or self.headers.get("X-Closure-Token")!=app.token:
                return self.respond({"error":"Invalid viewer write token"},403)
            origin=self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{self.server.server_port}",f"http://localhost:{self.server.server_port}"):
                return self.respond({"error":"Cross-origin writes are forbidden"},403)
            if self.headers.get('X-Closure-API', VIEWER_API) != VIEWER_API:
                return self.respond({"error":"Viewer API version mismatch; reload the bundled viewer"},409)
            try:
                length=int(self.headers.get("Content-Length","0"))
                if not 0<length<=1_000_000: raise ValueError("Invalid body length")
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict): raise ValueError("Request body must be an object")
                if self.path=="/api/open":
                    path=(app.workspace/body["path"]).resolve()
                    if not path.is_relative_to(app.workspace): raise ClosureError("Project is outside the viewer workspace", "PATH_ESCAPE")
                    selected=Project(path)
                    app.project=selected.root
                    app.manifest_path=selected.manifest_path
                    return self.respond(app.snapshot())
                if body.get("project")!=str(app.project.relative_to(app.workspace)):
                    return self.respond({"error":"Selected project changed; reload before writing"},409)
                if body.get("report"):
                    raise ClosureError("Historical snapshots are read-only. Return to the current project before changing it.", "HISTORY_READ_ONLY")
                if self.path=="/api/parameters":
                    result=patch_parameters(app.manifest_path,body["source_hash"],body["changes"])
                    return self.respond(result)
                if self.path in ("/api/build", "/api/verify"):
                    if not app.trusted: raise ClosureError("Start viewer with --trusted to enable project execution", "TRUST_REQUIRED")
                    force=body.get("force", False)
                    if not isinstance(force, bool): raise ValueError("force must be a boolean")
                    return self.respond(app.engine(body.get("scenario"),body.get("configuration")).verify(trusted=True, force=force))
                return self.respond({"error":"Unknown operation"},404)
            except (ClosureError,ValueError,OSError,KeyError) as exc:
                return self.respond({"error":exc.as_dict() if isinstance(exc,ClosureError) else str(exc)},400)
    server=LocalHTTPServer(("127.0.0.1",port),Handler)
    server.app=app
    return server


def serve(project,port=8765,workspace=None,trusted=False):
    server=create_server(project,port,workspace,trusted)
    print(f"Closure viewer: http://127.0.0.1:{server.server_port}",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
