"""Resolve local composition declarations before the ordinary module linker runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from .io import ClosureError, within
from .models import Manifest, Module


def manifest_path(path):
    path = Path(path).resolve()
    if not path.is_dir():
        return path
    candidates = [path / name for name in ("project.yaml", "project.yml", "project.json") if (path / name).is_file()]
    if len(candidates) > 1:
        raise ClosureError("Multiple project manifests; select one explicitly", "AMBIGUOUS_MANIFEST", str(path))
    return candidates[0] if candidates else path / "project.yaml"


def workspace_root(selected, boundary=None):
    for parent in (selected.parent, *selected.parent.parents):
        if (parent / ".closure-workspace").is_file() or (parent / ".git").exists():
            if boundary is None or parent.is_relative_to(boundary):
                return parent
        if parent == boundary:
            break
    return boundary or selected.parent


def locate(source, locator, workspace):
    if locator.startswith("file:"):
        url = urlsplit(locator)
        if url.netloc not in ("", "localhost") or url.query or url.fragment:
            raise ClosureError(f"Invalid local file URL {locator}", "LOCATOR", str(source))
        locator = url2pathname(url.path)
    elif "://" in locator:
        raise ClosureError(f"Unsupported project locator {locator}", "LOCATOR", str(source))
    path = manifest_path(source.parent / locator)
    if not path.is_relative_to(workspace):
        raise ClosureError(f"Project link escapes workspace: {locator}", "PATH_ESCAPE", str(source))
    if not path.is_file():
        raise ClosureError(f"Missing linked project {locator}", "MISSING_PROJECT", str(source))
    return path


@dataclass
class Unit:
    path: Path
    manifest: Manifest
    owned: bool = False
    imports: dict = field(default_factory=dict)
    children: dict = field(default_factory=dict)
    modules: list = field(default_factory=list)

    @property
    def name(self):
        return self.manifest.project

    def qualify(self, symbol):
        return f"{self.name}::{symbol}"

    def reference(self, symbol):
        if symbol.startswith("@"):
            if symbol[1:] not in self.imports:
                raise ClosureError(f"Unknown import {symbol} in {self.name}", "UNKNOWN_REF", str(self.path))
            return self.imports[symbol[1:]]
        return self.qualify(symbol)


class Composition:
    def __init__(self, project, manifest, workspace):
        self.workspace = workspace
        self.units = {}
        self._paths = {}
        self.root = self.discover(project, project.manifest_path, manifest)
        self.select(project, self.root, [])
        self.modules = {}
        for unit in self.units.values():
            for alias, (supplier, export) in list(unit.imports.items()):
                public = getattr(supplier.manifest, "exports", {})
                if export not in public:
                    raise ClosureError(f"{unit.name} import {alias}: {supplier.name} does not export {export}",
                                       "PRIVATE_REF", str(unit.path))
                unit.imports[alias] = supplier.qualify(public[export])
            seen = set()
            for pattern in unit.manifest.modules:
                within(unit.path.parent, pattern)
                for path in sorted(unit.path.parent.glob(pattern)):
                    path = within(unit.path.parent, path)
                    if path in seen:
                        continue
                    seen.add(path)
                    module = project._load(path, Module)
                    project._identifier(module.module)
                    unit.modules.append((path, module))
                    self.modules[unit.qualify(module.module)] = unit

    def discover(self, project, path, manifest=None):
        if path in self._paths:
            return self._paths[path]
        manifest = manifest or project._load(path, Manifest)
        project._identifier(manifest.project)
        if manifest.project in self.units:
            raise ClosureError(f"Conflicting project ID {manifest.project} at {path} and {self.units[manifest.project].path}",
                               "DUPLICATE_ID", str(path))
        unit = Unit(path, manifest)
        self.units[unit.name] = self._paths[path] = unit
        for alias, link in getattr(manifest, "imports", {}).items():
            project._identifier(alias)
            provider = self.discover(project, locate(path, link.path, self.workspace))
            unit.imports[alias] = (provider, link.export)
        return unit

    def select(self, project, unit, ancestors):
        if unit.name in ancestors:
            raise ClosureError("Containment cycle: " + " -> ".join([*ancestors, unit.name]),
                               "CONTAINMENT_CYCLE", str(unit.path))
        if unit.owned:
            return
        unit.owned = True
        for alias, link in getattr(unit.manifest, "children", {}).items():
            project._identifier(alias)
            if link.required:
                child = self.discover(project, locate(unit.path, link.path, self.workspace))
                unit.children[alias] = child.name
                self.select(project, child, [*ancestors, unit.name])

    def module_entries(self):
        from .project import criteria, refs
        for unit in self.units.values():
            for path, module in unit.modules:
                module.module = unit.qualify(module.module)
                for analysis in module.analyses.values():
                    bindings = list(analysis.inputs.values())
                    bindings.extend(b for condition in analysis.valid_when for b in refs(condition))
                    for binding in bindings:
                        binding.ref = unit.reference(binding.ref)
                for requirement in module.requirements.values():
                    for condition in criteria(requirement.verify):
                        for binding in refs(condition):
                            binding.ref = unit.reference(binding.ref)
                    requirement.derived_from = [unit.qualify(ref) for ref in requirement.derived_from]
                yield path, module

    def scope(self, requirements):
        result = []
        for unit in self.units.values():
            if not unit.owned:
                continue
            if unit.manifest.scope == ["*"]:
                result.extend(key for key, req in requirements.items() if key.startswith(unit.name + "::") and req.required)
            else:
                result.extend(unit.qualify(ref) for ref in unit.manifest.scope)
            result.extend(unit.reference("@" + alias) for alias in getattr(unit.manifest, "required_claims", []))
        return sorted(set(result))

    def local_scope(self, unit, requirements):
        scope = unit.manifest.scope
        local = [k for k, v in requirements.items() if k.startswith(unit.name + "::") and v.required] if scope == ["*"] else [unit.qualify(k) for k in scope]
        return local + [unit.reference("@" + alias) for alias in getattr(unit.manifest, "required_claims", [])]

    def policies(self, identifier):
        unit = self.modules[identifier.split(".")[0]]
        owners = {unit.name}
        for consumer in self.units.values():
            if consumer.owned and identifier in [consumer.reference("@" + a) for a in getattr(consumer.manifest, "required_claims", [])]:
                owners.add(consumer.name)
        pending = list(owners)
        while pending:
            child = pending.pop()
            for parent in self.units.values():
                if child in parent.children.values() and parent.name not in owners:
                    owners.add(parent.name)
                    pending.append(parent.name)
        return [self.units[name].manifest.policy for name in sorted(owners)]

    def gates(self, assessments, baselines, requirements):
        indexed = {r["id"]: r for r in assessments}
        gates = {}
        def evaluate(unit):
            if unit.name in gates:
                return gates[unit.name]
            scoped = self.local_scope(unit, requirements)
            children = [evaluate(self.units[name]) for name in unit.children.values()]
            applicable = sum(indexed[key]["applicability"] == "applicable" for key in scoped)
            applicable += sum(child["applicable"] for child in children)
            reasons = [key for key in scoped if not indexed[key]["gate_allowed"]]
            reasons.extend(child["project"] for child in children if not child["gate"])
            if baselines[unit.name]["status"] != "current":
                reasons.append("Obligation baseline " + baselines[unit.name]["status"])
            if not applicable:
                reasons.append("No applicable obligations")
            result = {"project": unit.name, "gate": not reasons, "applicable": applicable,
                      "scope": scoped, "reasons": reasons}
            gates[unit.name] = result
            return result
        evaluate(self.root)
        return gates

    def describe(self):
        return {unit.name: {"name": unit.manifest.name or unit.name, "source": unit.path.relative_to(self.workspace).as_posix(),
                            "owned": unit.owned, "children": unit.children, "imports": unit.imports,
                            "exports": getattr(unit.manifest, "exports", {}), "scope": unit.manifest.scope,
                            "excluded_children": [key for key, link in getattr(unit.manifest, "children", {}).items() if not link.required],
                            "policy": unit.manifest.policy.model_dump()}
                for unit in self.units.values()}

