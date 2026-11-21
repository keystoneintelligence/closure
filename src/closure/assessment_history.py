"""Engineering comparisons derived from sealed reports and their recorded inputs."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .io import ClosureError


def revision(workspace, files):
    """Describe Git's relationship to the exact files assessed, including ignored assets."""
    def git(*args):
        result = subprocess.run(["git", *args], cwd=workspace, capture_output=True)
        if result.returncode:
            raise ValueError
        return result.stdout.decode("utf-8", "surrogateescape")

    try:
        top = Path(git("rev-parse", "--show-toplevel").strip()).resolve()
        commit = git("rev-parse", "--verify", "HEAD").strip()
        tracked = set(git("ls-files", "--full-name", "-z", "--", ".").split("\0"))
        changed = set(git("diff", "--name-only", "--no-renames", "--no-ext-diff", "-z", "HEAD", "--", ".").split("\0"))
        evaluated = {p.relative_to(top).as_posix() for p in files if p.is_relative_to(top)}
        local = sorted((evaluated - tracked) | (evaluated & changed))
        return {"state": "local changes" if local else "committed inputs", "commit": commit, "files": local}
    except (OSError, ValueError):
        return {"state": "local snapshot", "commit": None, "files": []}


def previous_report(store, report):
    directory = store.root / "reports"
    compatible = []
    for path in directory.glob("*.json"):
        try:
            candidate = store.load_report(path.stem, artifacts=False)
        except (ClosureError, OSError):
            continue
        if (candidate["project"] == report["project"] and candidate["context"] == report["context"]
                and set(candidate["scope"]) == set(report["scope"]) and candidate["created_at"] < report["created_at"]):
            compatible.append(candidate)
    return max(compatible, key=lambda item: item["created_at"], default=None)


def display(value, unit):
    return f"{value:g} {unit or ''}".strip() if type(value) in (float, int) else str(value)


def contract_changes(before, after, path=""):
    """Render changed acceptance definitions, preserving field and project names."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [line for key in sorted(before.keys() | after.keys())
                for line in contract_changes(before.get(key), after.get(key), f"{path}.{key}" if path else key)]
    return [f"{path}: {before} → {after}"]


def compare_reports(before, after):
    if before and (before["project"] != after["project"] or before["context"] != after["context"]):
        raise ClosureError("Choose assessments of the same project and context", "COMPARISON_CONTEXT")
    changes = []
    old_rows = {r["id"]: r for r in before["requirements"]} if before else {}
    new_rows = {r["id"]: r for r in after["requirements"]}
    if before:
        for key in sorted(old_rows.keys() | new_rows.keys()):
            old, new = old_rows.get(key), new_rows.get(key)
            if not old or not new:
                changes.append(f"{key} was {'added' if new else 'removed'}.")
                continue
            detail = []
            for field in ("status", "text", "owner", "acceptance", "scoped"):
                if old[field] != new[field]:
                    detail.append(f"{field} changed from {old[field]} to {new[field]}")
            for left, right in zip(old["comparisons"], new["comparisons"]):
                changed = False
                for field in ("actual", "limit", "margin", "op", "ref"):
                    if left.get(field) != right.get(field) or left.get("unit") != right.get("unit"):
                        detail.append(f"{field} changed from {display(left.get(field), left.get('unit'))} to {display(right.get(field), right.get('unit'))}")
                        changed = True
                if changed and left["actual"] == right["actual"] and left.get("unit") == right.get("unit"):
                    detail.append(f"calculated value stayed at {display(right['actual'], right.get('unit'))}")
            if detail:
                changes.append(f"{key} ({new['owner']}): " + ". ".join(detail) + ".")
        for name in sorted(before.get("projects", {}).keys() | after.get("projects", {}).keys()):
            a, b = before.get("projects", {}).get(name, {}), after.get("projects", {}).get(name, {})
            for field in ("owned", "children", "imports", "exports", "scope", "policy", "excluded_children"):
                if a.get(field) != b.get(field):
                    changes.append(f"{name}: {field.replace('_', ' ')} changed from {a.get(field)} to {b.get(field)}.")
    old_runs = {a["id"]: a.get("record") for a in before["analyses"]} if before else {}
    decisions = []
    for analysis in after["analyses"]:
        key, record = analysis["id"], analysis["record"]
        if analysis["state"] != "current" or not record:
            reason = (analysis.get("error") or {}).get("message") or f"Evidence is {analysis['state']}."
        elif key not in after["executed"]:
            reason = f"Reused the verified run from {record['finished_at']}. Declared dependencies and execution context matched."
        else:
            old = old_runs.get(key)
            differences = []
            if old:
                for field in ("sources", "inputs", "upstream", "tools", "settings", "environment"):
                    left, right = old[field], record[field]
                    differences.extend(f"{field}: {name}" for name in sorted(left.keys() | right.keys()) if left.get(name) != right.get(name))
                for field in ("command", "seed"):
                    if old[field] != record[field]:
                        differences.append(field)
            reason = ("Ran with changes to " + ", ".join(differences) + "." if differences else
                      "Ran again with the same execution key." if old and old["execution_key"] == record["execution_key"] else
                      "Ran with a changed execution contract." if old else "Ran to establish evidence for this assessment.")
        decisions.append({"analysis": key, "reason": reason, "run": record["id"] if record else None})
    return {"previous": before["id"] if before else None, "previous_date": before["created_at"] if before else None,
            "changes": changes, "decisions": decisions}

