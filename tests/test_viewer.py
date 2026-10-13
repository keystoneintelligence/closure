"""Exercise the real HTTP boundary, including edits and fail-closed gates."""
import json
import shutil
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from closure.engine import Engine
from closure.io import file_digest
from closure.viewer_server import create_server
from closure.viewer_server import VIEWER_API
from closure import __version__
from conftest import edit_yaml
from test_rfc_acceptance import artifact_analysis, input_power


@pytest.fixture
def viewer(project_dir):
    server = create_server(project_dir, port=0, workspace=project_dir.parent, trusted=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request_headers = {"X-Closure-Token": server.app.token, "Content-Type": "application/json"}
        request_headers.update(headers or {})
        req = Request(f"http://127.0.0.1:{server.server_port}{path}", data=data, headers=request_headers)
        try:
            response = urlopen(req, timeout=30)
        except HTTPError as exc:
            response = exc
        with response:
            content = response.read()
            if response.headers.get_content_type() == "application/json":
                content = json.loads(content)
            return response.status, content, response.headers
    yield server, request
    server.shutdown()
    server.server_close()
    thread.join(5)


def test_viewer_edits_stales_builds_and_explains(viewer, project_dir):
    server, request = viewer
    _, snapshot, _ = request("/api/project")
    identity = {"project": snapshot["path"]}
    status, built, _ = request("/api/build", identity)
    assert status == 200 and built["gate"]
    status, edit, _ = request("/api/parameters", {
        **identity, "source_hash": built["source_hash"],
        "changes": {"payload.peak_power": {"value": 120, "unit": "W"}}})
    assert status == 200 and edit["changed"] == ["payload.peak_power"]
    _, stale, _ = request("/api/project")
    assert stale["report"]["requirements"][0]["status"] == "STALE"
    _, failed, _ = request("/api/build", identity)
    assert not failed["gate"]
    _, explanation, _ = request("/api/explain?id=power.PWR-001")
    assert explanation["requirement"]["comparisons"][0]["margin"] == -20
    assert any("payload.peak_power" in path for path in explanation["paths"])
    _, history, _ = request("/api/history")
    assert len(history["runs"]) == 2
    _, source, _ = request("/api/source?module=payload")
    assert "120" in source["text"]


def test_viewer_verify_can_force_current_evidence(viewer):
    server, request = viewer
    _, snapshot, _ = request('/api/project')
    body = {'project':snapshot['path']}
    status, first, _ = request('/api/verify',body)
    assert status == 200 and first['gate']
    assert request('/api/verify',body)[1]['executed'] == []
    status, forced, _ = request('/api/verify',{**body,'force':True})
    assert status == 200 and forced['executed'] == ['power.budget']
    assert forced['analyses'][0]['record']['id'] != first['analyses'][0]['record']['id']
    assert request('/api/verify',{**body,'force':'yes'})[0] == 400


def test_viewer_rejects_cross_origin_or_stale_writes(viewer):
    server, request = viewer
    _, snapshot, _ = request("/api/project")
    body = {"project": snapshot["path"]}
    assert request("/api/build", body, {"X-Closure-Token": "invalid"})[0] == 403
    assert request("/api/build", body, {"Origin": "https://other.example"})[0] == 403
    assert request("/api/project", headers={"Host": "other.example"})[0] == 403
    assert request("/api/build", {"project": "other"})[0] == 409
    assert request("/api/parameters", {**body, "source_hash": "old", "changes": {}})[0] == 400
    assert request("/api/build", ["invalid"])[0] == 400
    server.app.trusted = False
    status, result, _ = request("/api/build", body)
    assert status == 400 and result["error"]["code"] == "TRUST_REQUIRED"


def test_viewer_opens_a_second_project_with_custom_contexts(viewer, project_dir):
    server, request = viewer
    second = project_dir.parent / "second"
    shutil.copytree(project_dir, second)
    edit_yaml(second / "project.yaml", lambda d: d.update(
        project="service-capacity", scenarios={"peak": {}}, configurations={"production": {}}))
    edit_yaml(second / "model/power.yaml", lambda d: d["requirements"]["PWR-001"].update(
        applies_to=["peak"], configurations=["production"]))
    status, snapshot, _ = request("/api/open", {"path": "second"})
    assert status == 200
    assert snapshot["report"]["context"] == {"scenario": "peak", "configuration": "production", "point": "baseline"}
    assert snapshot["project"]["project"] == "service-capacity"
    assert request("/api/open", {"path": ".."})[0] == 400
    assert request("/%2e%2e/engine.py")[0] == 403


def test_viewer_serves_only_project_artifacts_and_bundled_assets(viewer, project_dir):
    server, request = viewer
    asset = project_dir / "drawing.step"
    asset.write_bytes(b"ISO-10303-21; fixture")
    edit_yaml(project_dir / "model/payload.yaml", lambda d: d["parameters"].update(
        drawing={"type": "artifact", "path": "drawing.step"}))
    status, data, headers = request("/api/artifacts/" + file_digest(asset) + "?type=text/html")
    assert status == 200 and data == asset.read_bytes()
    assert headers.get_content_type() == "application/octet-stream"
    assert request("/api/artifacts/" + "0" * 64)[0] == 404
    assert request("/api/artifacts/invalid")[0] == 400
    status, page, headers = request("/")
    assert status == 200 and b'app.js' in page
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert request("/app.js")[0] == 200


def test_viewer_history_preserves_model_values_and_explanations(viewer, project_dir):
    server, request = viewer
    built = Engine(project_dir).build(trusted=True)
    input_power(project_dir, 120)
    _, current, _ = request("/api/project")
    assert current["mode"] == "current" and not current["report"]["gate"]
    status, saved, _ = request("/api/project?report=" + built["id"])
    assert status == 200 and saved["mode"] == "historical"
    assert saved["report"]["gate"]
    module = next(m for m in saved["modules"] if m["module"] == "payload")
    assert module["parameters"]["peak_power"]["value"] == 80
    _, source, _ = request("/api/source?module=payload&report=" + built["id"])
    assert json.loads(source["text"])["parameters"]["peak_power"]["value"] == 80
    _, explained, _ = request("/api/explain?id=power.PWR-001&report=" + built["id"])
    assert explained["requirement"]["comparisons"][0]["actual"] == 180
    assert request("/api/build", {"project": saved["path"], "report": built["id"]})[0] == 400
    _, history, _ = request("/api/history")
    assert history["reports"][0]["id"] == built["id"]
    _, record, _ = request("/api/runs?id=" + history["runs"][0]["id"])
    assert record["run"]["outputs"]["total"]["value"] == 180


def test_viewer_refuses_artifacts_whose_bytes_changed(viewer, project_dir):
    server, request = viewer
    artifact_analysis(project_dir)
    built = Engine(project_dir).build(trusted=True)
    output = next(v for v in built["analyses"][0]["record"]["outputs"].values() if v["type"] == "artifact")
    Path(output["path"]).write_bytes(b"corrupt")
    status, response, _ = request("/api/artifacts/" + output["sha256"])
    assert status == 400 and response["error"]["code"] == "ARTIFACT_CORRUPT"
    assert request("/api/project?report=" + built["id"])[0] == 400


def test_viewer_port_has_only_one_server(viewer, project_dir):
    server, request = viewer
    with pytest.raises(OSError):
        create_server(project_dir, port=server.server_port)
    assert request("/api/project")[0] == 200


def test_viewer_version_negotiation_prevents_incompatible_writes(viewer):
    server, request = viewer
    status, metadata, headers = request('/api/version')
    assert status == 200 and metadata['api'] == VIEWER_API
    assert metadata['implementation'] == __version__
    assert headers['X-Closure-API'] == VIEWER_API
    bad = {'X-Closure-API': 'closure-viewer/999'}
    assert request('/api/project', headers=bad)[0] == 409
    assert request('/api/open', {'path':'.'}, bad)[0] == 409
    assert request('/api/version', headers={'X-Closure-API':VIEWER_API})[0] == 200
