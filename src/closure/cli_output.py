"""Human presentation only; versioned JSON remains the engine's unchanged output."""
from __future__ import annotations

import os
import shlex
from pathlib import Path


def scalar(value):
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def quote(value):
    return "'" + str(value).replace("'", "''") + "'" if os.name == "nt" else shlex.quote(str(value))


def datum(value):
    if value.get("type") == "artifact" or value.get("path"):
        return value.get("path") or value.get("name", "artifact")
    return f"{scalar(value.get('value'))} {value.get('unit') or ''}".rstrip()


def tree(value, indent=0):
    """Compact nested contracts without losing meaningful zero/false values."""
    lines, pad = [], " " * indent
    if isinstance(value, dict):
        if "ref" in value and set(value) <= {"ref", "unit", "qualifiers"}:
            return [pad + value["ref"] + (f" in {value['unit']}" if value.get("unit") else "")]
        for key, item in value.items():
            if item is None or item == "" or item == [] or item == {}:
                continue
            label = key.replace("_", " ")
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{label}:")
                lines.extend(tree(item, indent + 2))
            else:
                lines.append(f"{pad}{label}: {scalar(item)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                lines.extend(tree(item, indent + 2))
            else:
                lines.append(f"{pad}- {scalar(item)}")
    else:
        lines.append(pad + scalar(value))
    return lines


def assessment_lines(item):
    suffix = " (outside selected scope)" if item.get("scoped") is False else ""
    lines = [f"{item['status']:12} {item['id']}{suffix}", f"  {item['text']}"]
    operators = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "eq": "=", "ne": "!="}
    alternative = item.get("verification_mode") == "any_of"
    if alternative:
        lines.append("  Any one alternative may provide support:")
        for branch in item["branches"]:
            selected = " (selected)" if branch["index"] in item["selected_branches"] else ""
            policy = " (evidence disallowed)" if not branch["evidence_allowed"] else ""
            lines.append(f"    Alternative {branch['index'] + 1}: {branch['verdict'].upper()}{selected}{policy}")
    for comparison in item.get("comparisons", []):
        if comparison.get("actual") is None:
            lines.append(f"  {comparison['ref']}: no current result")
            continue
        unit = comparison.get("unit") or ""
        margin = comparison.get("margin")
        margin_text = f"; margin {scalar(margin)} {unit}" if margin is not None else ""
        prefix = f"Alternative {comparison['branch'] + 1}: " if alternative else ""
        lines.append(f"  {prefix}{scalar(comparison['actual'])} {unit}; required "
                     f"{operators.get(comparison.get('op'), '')} {scalar(comparison['limit'])} {unit}{margin_text}".rstrip())
    return lines


def report_lines(value, command, root, verbose):
    context = value["context"]
    lines = [f"{value['name']} | {context['scenario']} / {context['configuration']}",
             f"Gate: {'PASS' if value['gate'] else 'OPEN'} | Policy: {value['policy']['name']} | Baseline: {value['baseline']['status']}", ""]
    project_flag = f" --project {quote(root)}" if root else ""
    executed = set(value.get("executed", []))
    analyses = value["analyses"]
    planning = command == "plan"
    for analysis in analyses:
        state = analysis["state"]
        action = ("WILL RUN" if analysis["will_run"] else "CACHED") if planning else (
            "RAN" if analysis["id"] in executed else "CACHED" if state == "current" else state.upper())
        lines.append(f"{action:12} {analysis['id']}" + (f" ({state})" if planning and analysis["will_run"] else ""))
        if analysis.get("error"):
            lines.append(f"  {analysis['error']['code']}: {analysis['error']['message']}")
        if verbose and analysis.get("record"):
            record = analysis["record"]
            lines.append(f"  Run: {record['id']}")
            for name in ("inputs", "outputs"):
                lines.append(f"  {name}:")
                for key, item in record.get(name, {}).items():
                    lines.append(f"    {key}: {datum(item)}")
    cached = sum(a["state"] == "current" and a["id"] not in executed for a in analyses)
    if planning:
        lines.append(f"Plan: {sum(a['will_run'] for a in analyses)} to run, {cached} reusable. No analyses executed.")
    else:
        failed = sum(a["state"] == "error" for a in analyses)
        blocked = sum(a["state"] == "blocked" for a in analyses)
        lines.append(f"Execution: {len(executed)} ran, {cached} reused, {failed} errors, {blocked} blocked.")
    lines.append("")
    for assessment in value["requirements"]:
        lines.extend(assessment_lines(assessment))
    if value["baseline"]["status"] != "current":
        lines.extend(["", value["baseline"]["message"], "Next: review the obligations, then use closure approve-baseline --help."])
    if planning:
        lines.extend(["", "Next: closure verify --trusted" + context_flags(context) + project_flag])
    elif "report_hash" in value:
        lines.extend(["", f"Report: {value['id']}"])
        if root:
            lines.append(f"Saved: {Path(root) / '.closure' / 'reports' / (value['id'] + '.json')}")
    if not value["gate"]:
        unclosed = next((a for a in value["requirements"] if a.get("scoped", True) and not a["gate_allowed"]), None)
        if unclosed:
            lines.append(f"Explain: closure explain {unclosed['id']}" + context_flags(context) + project_flag)
    comparison = value.get("base_comparison")
    if comparison:
        lines.extend(["", f"Compared with {comparison['ref']} ({comparison['commit'][:12]})",
                      "Changed files: " + (", ".join(comparison["changed_files"]) or "none"),
                      "Affected analyses: " + (", ".join(comparison["affected_analyses"]) or "none"),
                      "Affected requirements: " + (", ".join(comparison["affected_requirements"]) or "none"),
                      f"Obligations changed: {scalar(comparison['obligations_changed'])}"])
    return lines


def context_flags(context):
    return "".join(f" --{name} {quote(context[name])}" for name in ("scenario", "configuration") if context.get(name))


def render(value, command=None, root=None, verbose=False):
    if "gate" in value and "requirements" in value:
        lines = report_lines(value, command, root, verbose)
    elif command == "check":
        lines = [f"{'VALID' if value['valid'] else 'INVALID'}  {value['project']}",
                 f"{len(value['analyses'])} analyses, {value['requirements']} requirements"]
        for item in value["diagnostics"]:
            lines.append(f"{item.get('severity', 'error').upper()} {item['code']}: {item['message']} ({item.get('location', '')})")
        lines.append("Next: closure plan")
    elif command == "inspect":
        lines = [value["id"], f"Source: {value['source'] or 'derived output'}", *tree(value["contract"])]
    elif command == "impact":
        lines = [f"Changing {value['changed']} can affect {len(value['affected'])} downstream elements:"]
        lines += [f"  {item}" for item in value["affected"]]
        lines.append("Requirements: " + (", ".join(value["requirements"]) or "none"))
    elif command == "explain":
        item = value["requirement"]
        lines = assessment_lines(item)
        lines += [f"Evidence: {item['freshness']} | Execution: {item['execution']} | Acceptance: {item['acceptance']}",
                  f"Baseline: {value['baseline']['status']}", "Dependency paths:"]
        lines += ["  " + " -> ".join(path) for path in value["paths"]]
        if item.get("evidence"):
            lines.append("Evidence runs: " + ", ".join(item["evidence"]))
        if verbose:
            lines.extend(tree(item))
    elif command in ("patch", "set"):
        lines = []
        if command == "set":
            lines.append(f"{value['changed'][0]}: {datum(value['before'])} -> {datum(value['after'])}")
            lines.append("Saved base value. Scenario and configuration overrides still take precedence.")
        else:
            lines.append("Updated: " + ", ".join(value["changed"]))
        affected = sorted({i for impact in value["impact"] for i in impact["affected"]})
        lines.append(f"{len(affected)} downstream elements may be affected:")
        lines.extend("  " + i for i in affected)
        if value.get("obligation_change"):
            lines.append("This input defines a requirement limit; the changed baseline needs review.")
        lines.append("Next: closure plan, then closure verify --trusted")
    elif command == "format":
        label = "Formatted" if value["formatted"] else "Needs formatting"
        lines = ["Formatting is current." if value["clean"] else f"{label}: {len(value['files'])} files"]
        lines.extend("  " + name for name in value["files"])
    elif command == "init":
        lines = [f"Created project: {value['created']}", "Next: review project.yaml and model/, then record the initial baseline.", value["next"]]
    elif command == "schema":
        lines = [f"Schemas written to {value['schemas']}"]
    elif command == "export":
        lines = [f"Exported report: {value['report']}", f"Open: {Path(value['directory']) / 'index.html'}", f"Artifacts: {value['artifacts']}"]
    elif command == "sweep":
        lines = [f"Study: {value['study']}", f"{value['completed']}/{value['expected']} completed | {value['passed']} passing | {value['failed']} open",
                 f"Complete evidence: {scalar(value['complete_evidence'])}"]
        for report in value["reports"]:
            c = report["context"]
            lines.append(f"{'PASS' if report['gate'] else 'OPEN':8} {c['point']} | {c['scenario']} / {c['configuration']} | {report['id']}")
    elif command == "history" and "report" in value:
        lines = ["Saved snapshot (not current project state)", *report_lines(value["report"], "history", root, verbose)]
    elif command == "history" and "run" in value:
        run = value["run"]
        lines = [f"Saved run: {run['id']}", f"Analysis: {run['analysis']}", f"Started: {run['started_at']}"]
        lines += tree({k: run[k] for k in ("context", "inputs", "outputs")})
        if verbose:
            lines += tree({k: run[k] for k in ("sources", "command", "tools", "settings", "environment", "logs") if k in run})
    elif command == "history":
        lines = []
        for key in ("reports", "runs"):
            entries = value[key]
            lines.append(f"{key.capitalize()}: {len(entries)} (latest 10; --json includes all)")
            for item in entries[:10]:
                if item["integrity"] == "unavailable":
                    lines.append(f"  UNAVAILABLE {item['id']}  {item['error']['message']}")
                else:
                    status = ("PASS" if item["gate"] else "OPEN") if key == "reports" else item["analysis"]
                    lines.append(f"  {item['id']}  {item.get('created_at') or item.get('started_at')}  {status}")
        lines.append("Inspect: closure history --report ID or closure history --run ID")
    elif command in ("review", "approve-baseline"):
        lines = [f"Recorded {command}: {value.get('decision', 'approved')}", f"Reviewer: {value['reviewer']}", f"Reason: {value['reason']}"]
    else:
        lines = tree(value)
    return "\n".join(lines)
