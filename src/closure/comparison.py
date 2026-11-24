"""Read-only semantic comparison of a project against a committed Git tree."""
from __future__ import annotations

import shutil
import subprocess
import tarfile
import tempfile
from itertools import product
from pathlib import Path

from .evidence import source_snapshot
from .io import ClosureError, canonical, digest, file_digest, within
from .project import Project


def _git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise ClosureError(result.stderr.strip() or "Git operation failed", "GIT_BASE")
    return result.stdout.strip()


def _changes(before, after):
    return [{"id": name, "change": "added" if name not in before else "removed" if name not in after else "modified",
             "before": before.get(name), "after": after.get(name)}
            for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]


def _context_names(project):
    scenarios = set(project.manifest.scenarios)
    configurations = set(project.manifest.configurations)
    if project.composition:
        for unit in project.composition.units.values():
            scenarios.intersection_update(unit.manifest.scenarios)
            configurations.intersection_update(unit.manifest.configurations)
    return scenarios, configurations


def _context_impact(base, project):
    changed_inputs = set()
    if base.source_hash == project.source_hash:
        return False, changed_inputs
    old_scenarios, old_configs = _context_names(base)
    new_scenarios, new_configs = _context_names(project)
    for scenario, config in product(old_scenarios | new_scenarios, old_configs | new_configs):
        before = base.context_overrides(scenario, config) if scenario in old_scenarios and config in old_configs else {}
        after = project.context_overrides(scenario, config) if scenario in new_scenarios and config in new_configs else {}
        if not before and not after:
            continue
        # Omitted fields inherit from the parameter. An explicit default can
        # therefore change an input even when the two override models compare equal.
        declarations = [{k: canonical(v.model_dump(exclude_unset=True)) for k, v in overrides.items()}
                        for overrides in (before, after)]
        changes = _changes(*declarations)
        if changes:
            old_values = base.resolve_parameters(before)
            new_values = project.resolve_parameters(after)
            for change in changes:
                key = change["id"]
                if canonical(old_values.get(key)) != canonical(new_values.get(key)):
                    changed_inputs.add(key)
    names_changed = old_scenarios != new_scenarios or old_configs != new_configs
    return names_changed or bool(changed_inputs), changed_inputs


def compare_git(project: Project, ref: str):
    """Compare contracts and declared/transitive sources without importing project code.

    Git is optional: it supplies a source baseline, never evidence acceptance.
    The archive is extracted manually and cannot install links or escape its root.
    """
    root = Path(_git(project.root, "rev-parse", "--show-toplevel")).resolve()
    commit = _git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    boundary = project.workspace if project.composition else project.root
    prefix = boundary.relative_to(root).as_posix()
    tree = commit if prefix == "." else f"{commit}:{prefix}"
    changed = _git(root, "diff", "--name-only", "-z", "--no-ext-diff", "--no-textconv", commit, "--", prefix).split("\0")
    changed += _git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", prefix).split("\0")
    changed = [name for name in changed if name]
    relative_changes = {Path(name).relative_to(prefix).as_posix() if prefix != "." else name.replace("\\", "/") for name in changed}
    with tempfile.TemporaryDirectory(prefix="closure-base-") as directory:
        snapshot = Path(directory) / "source"
        snapshot.mkdir()
        archive = Path(directory) / "base.tar"
        with archive.open("wb") as output:
            result = subprocess.run(["git", "archive", "--format=tar", tree], cwd=root, stdout=output, stderr=subprocess.PIPE)
        if result.returncode:
            raise ClosureError(result.stderr.decode(errors="replace"), "GIT_BASE")
        if archive.stat().st_size > 512_000_000:
            raise ClosureError("Git project snapshot exceeds the 512 MB comparison limit", "BASE_LIMIT")
        with tarfile.open(archive) as contents:
            for member in contents:
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ClosureError(f"Git baseline contains a link or special file: {member.name}", "BASE_UNSAFE")
                target = within(snapshot, member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with contents.extractfile(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        try:
            base = Project(snapshot / project.manifest_path.relative_to(boundary), workspace=snapshot)
        except ClosureError as exc:
            raise ClosureError(f"Cannot compile Git baseline: {exc}", "BASE_INVALID") from exc
        before = {section: {k: v.model_dump() for k, v in getattr(base, section).items()}
                  for section in ("parameters", "analyses", "requirements")}
        after = {section: {k: v.model_dump() for k, v in getattr(project, section).items()}
                 for section in before}
        changes = {section: _changes(before[section], after[section]) for section in before}
        sources = []
        for identifier in sorted(base.analyses.keys() | project.analyses.keys()):
            snapshots = []
            for version in (base, project):
                if identifier not in version.analyses:
                    snapshots.append({})
                else:
                    try:
                        snapshots.append(source_snapshot(version, version.analyses[identifier], version.source_root(identifier)))
                    except ClosureError as exc:
                        raise ClosureError(f"Cannot compare {identifier}: {exc}", "BASE_SOURCE") from exc
            # Git normalizes tracked text (e.g. Windows autocrlf). Its change set
            # decides whether an existing path changed; raw hashes still identify
            # the two versions of changed dependencies and all added/removed paths.
            files = [change for change in _changes(*snapshots)
                     if change["change"] != "modified" or (project.source_root(identifier).relative_to(boundary) / change["id"]).as_posix() in relative_changes]
            if files:
                sources.append({"analysis": identifier, "files": files})
        artifact_changes = []
        for identifier in sorted(base.parameters.keys() | project.parameters.keys()):
            hashes = []
            for version in (base, project):
                datum = version.parameters.get(identifier)
                path = within(version.source_root(identifier), datum.path) if datum and datum.type == "artifact" else None
                hashes.append(file_digest(path) if path and path.is_file() else None)
            if hashes[0] != hashes[1]:
                artifact_changes.append({"id": identifier, "before": hashes[0], "after": hashes[1]})
        context_changed, changed_inputs = _context_impact(base, project)
        seeds = {c["id"] for items in changes.values() for c in items}
        seeds.update(c["analysis"] for c in sources)
        seeds.update(c["id"] for c in artifact_changes)
        seeds.update(changed_inputs)
        affected = set(seeds)
        for version in (base, project):
            for identifier in seeds:
                if identifier in version.locations or identifier in version.ports:
                    affected.update(version.impact(identifier)["affected"])
        moved = [{"module": identifier, "before": str(Path(base.locations[identifier]).relative_to(base.workspace if base.composition else base.root)).replace("\\", "/"),
                  "after": str(Path(project.locations[identifier]).relative_to(boundary)).replace("\\", "/")}
                 for identifier in sorted(base.modules.keys() & project.modules.keys())
                 if Path(base.locations[identifier]).relative_to(base.workspace if base.composition else base.root) != Path(project.locations[identifier]).relative_to(boundary)]
        return {"ref": ref, "commit": commit, "changed_files": sorted(set(changed)),
                "changes": changes, "source_changes": sources, "artifact_changes": artifact_changes, "moved_modules": moved,
                "context_changed": context_changed,
                "project_changes": _changes(base.composition.describe() if base.composition else {}, project.composition.describe() if project.composition else {}),
                "obligations_changed": digest(base.obligation_contract()) != digest(project.obligation_contract()),
                "affected_analyses": sorted(affected & (base.analyses.keys() | project.analyses.keys())),
                "affected_requirements": sorted(affected & (base.requirements.keys() | project.requirements.keys())),
                "interpretation": "Potential impact relative to the committed source tree; current evidence and reviewed obligations determine the gate."}
