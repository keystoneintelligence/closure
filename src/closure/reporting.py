"""Portable, inspectable report bundles with verified artifact copies."""
from __future__ import annotations

import html
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

from .engine import Engine
from .evidence import EvidenceStore
from .io import ClosureError, atomic_json, file_digest


def explain_saved_report(report, identifier):
    requirement = next((r for r in report["requirements"] if r["id"] == identifier), None)
    if requirement is None:
        raise ClosureError(f"Unknown requirement in this snapshot: {identifier}", "UNKNOWN_REF")
    paths = []
    def trace(node, suffix, visited):
        if node in visited:
            return
        parents = [edge["source"] for edge in report["model"]["edges"]
                   if edge["target"] == node and edge["kind"] in ("consumes", "produces", "verifies")]
        if not parents:
            paths.append([node, *suffix])
        for parent in parents:
            trace(parent, [node, *suffix], visited | {node})
    trace(identifier, [], set())
    return {"requirement": requirement, "paths": paths, "context": report["context"],
            "baseline": report["baseline"], "snapshot": report["id"]}


def export_report(engine, destination, report_id=None):
    if report_id:
        root = engine.project.root if isinstance(engine, Engine) else Path(engine).resolve()
        store = EvidenceStore(root if root.is_dir() else root.parent)
        report = store.load_report(report_id)
    else:
        engine = engine if isinstance(engine, Engine) else Engine(engine)
        store = engine.store
        report = engine.plan()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ClosureError("Report destination already exists; choose a new folder", "OUTPUT_EXISTS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="closure-report-", dir=destination.parent) as directory:
        stage = Path(directory) / "bundle"
        stage.mkdir()
        artifacts = []
        for analysis in report["analyses"]:
            record = analysis.get("record")
            if not record:
                continue
            entries = [(name, value, "output") for name, value in record["outputs"].items()]
            if record.get("inputs_archived"):
                entries.extend((name, value, "input") for name, value in record["inputs"].items())
            for name, value, role in entries:
                if value.get("type") != "artifact":
                    continue
                relative = Path("artifacts") / (value["sha256"][:16] + "-" + Path(value["name"]).name)
                target = stage / relative
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(store.artifact_path(value), target)
                if file_digest(target) != value["sha256"]:
                    raise ClosureError("Artifact changed during report export", "ARTIFACT_CONFLICT")
                identifier = f"{analysis['id']}.{name}" if role == "output" else f"{analysis['id']}.inputs.{name}"
                artifacts.append({"id": identifier, "role": role, "file": relative.as_posix(),
                                  "sha256": value["sha256"], "media_type": value.get("media_type"), "run": record["id"]})
        atomic_json(stage / "report.json", report)
        atomic_json(stage / "artifacts.json", {"schema": "closure-export/0.1", "report": report["id"],
                    "mode": "historical" if report_id else "current_plan", "report_hash": report.get("report_hash"), "artifacts": artifacts})
        esc = lambda x: html.escape(str(x))
        rows = []
        for requirement in report["requirements"]:
            comparisons = "<br>".join(esc(f"{c.get('actual')} {c.get('unit') or ''} {c.get('op', '')} {c.get('limit')} | margin {c.get('margin')}")
                                        for c in requirement["comparisons"])
            rows.append(f"<tr><td>{esc(requirement['status'])}</td><td><code>{esc(requirement['id'])}</code><br>{esc(requirement['text'])}</td>"
                        f"<td>{comparisons or 'No current comparison'}</td><td>{'Included' if requirement['scoped'] else 'Excluded'}</td></tr>")
        links = "".join(f'<li><a href="{quote(a["file"])}">{esc(a["id"])}</a><br><small>{esc(a["sha256"])}</small></li>' for a in artifacts)
        assumptions = "".join(f"<li>{esc(a['id'])}: {esc(a['rationale'])}</li>" for a in report.get("assumptions", []))
        page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(report['name'])} — Closure evidence report</title><style>
body{{font:16px/1.55 system-ui,sans-serif;background:#edf3f6;color:#203949;margin:0;padding:40px}}main{{max-width:1100px;margin:auto}}
h1{{font-size:34px;letter-spacing:-1px}}.gate{{padding:20px;background:{'#d8f0e6' if report['gate'] else '#fff0d9'};border-radius:12px}}
table{{width:100%;border-collapse:collapse;background:white}}td,th{{padding:14px;text-align:left;border-bottom:1px solid #dce5ea;vertical-align:top}}
code,small{{overflow-wrap:anywhere}}a{{color:#087d67}}li{{margin-bottom:14px}}@media(max-width:650px){{body{{padding:16px}}table{{font-size:13px}}td,th{{padding:8px}}}}
</style><main><p>CLOSURE · ENGINEERING EVIDENCE</p><h1>{esc(report['name'])}</h1>
<div class="gate"><strong>{'Recorded scope closed' if report_id and report['gate'] else 'Selected scope closed' if report['gate'] else 'Closure needs attention'}</strong><br>
Policy: {esc(report['policy']['name'])} · {esc(report['context']['configuration'])} / {esc(report['context']['scenario'])}<br>
{esc(report['baseline']['message'])}</div><p><strong>{'Historical build snapshot' if report_id else 'Current plan snapshot'}</strong> · {esc(report['created_at'])}<br>
This report records support at the stated time and context. Re-plan the source project to check current support.
{'Its report digest and artifact hashes were checked during export.' if report_id else ''}</p>
<h2>Requirements and declared scope</h2><table><thead><tr><th>Status</th><th>Requirement</th><th>Comparison</th><th>Scope</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>Artifacts</h2><ul>{links or '<li>No current artifact evidence.</li>'}</ul><h2>Assumptions</h2><ul>{assumptions or '<li>See source contracts and the JSON report.</li>'}</ul>
<h2>Limitations</h2><ul>{''.join('<li>'+esc(x)+'</li>' for x in report['limitations'])}</ul>
<p><a href="report.json">Complete report and run provenance</a> · <a href="artifacts.json">Artifact content manifest</a></p></main></html>'''
        (stage / "index.html").write_text(page, encoding="utf-8")
        # Publish the complete bundle only when all copied artifacts have verified.
        if destination.exists():
            raise ClosureError("Report destination appeared during export", "OUTPUT_EXISTS")
        os.rename(stage, destination)
    return {"directory": str(destination), "report": report["id"], "gate": report["gate"], "artifacts": len(artifacts),
            "mode": "historical" if report_id else "current_plan", "report_hash": report.get("report_hash")}
