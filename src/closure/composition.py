"""Resolve local composition declarations before the ordinary module linker runs."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from .io import ClosureError, within
from .models import Analysis, CompositionManifest, Manifest, Module, Requirement


def manifest_path(path):
    path = Path(path).resolve()
    if not path.is_dir():
        return path
    candidates = [path / name for name in ("project.yaml", "project.yml", "project.json") if (path / name).is_file()]
    if len(candidates) > 1:
        raise ClosureError("Multiple project manifests; select one explicitly", "AMBIGUOUS_MANIFEST", str(path))
    return (candidates[0] if candidates else path / "project.yaml").resolve()


def workspace_root(selected, boundary=None):
    for parent in (selected.parent, *selected.parent.parents):
        if (parent / ".closure-workspace").is_file() or (parent / ".git").exists():
            if boundary is None or parent.is_relative_to(boundary):
                return parent
        if parent == boundary:
            break
    return boundary or selected.parent


def locate(source, locator, workspace, dependency=None):
    if locator.startswith("file:"):
        url = urlsplit(locator)
        if url.netloc not in ("", "localhost") or url.query or url.fragment:
            raise ClosureError(f"Invalid local file URL {locator}", "LOCATOR", str(source))
        locator = url2pathname(url.path)
    elif "://" in locator:
        raise ClosureError(f"Unsupported project locator {locator}", "LOCATOR", str(source))
    path = manifest_path(within(workspace, source.parent / locator))
    if not path.is_relative_to(workspace):
        raise ClosureError(f"Project link escapes workspace: {locator}", "PATH_ESCAPE", str(source))
    if not path.is_file():
        detail = f" for {dependency}" if dependency else ""
        raise ClosureError(f"Missing linked project {locator}{detail}", "MISSING_PROJECT", str(source))
    return path


def contract_bindings(contract):
    from .project import criteria, refs
    if isinstance(contract, Analysis):
        yield from contract.inputs.values()
        conditions = contract.valid_when
    else:
        conditions = criteria(contract.verify)
    for condition in conditions:
        yield from refs(condition)


@dataclass
class Unit:
    path: Path
    manifest: Manifest
    owned: bool = False
    imports: dict = field(default_factory=dict)
    children: dict = field(default_factory=dict)
    modules: list = field(default_factory=list)
    symbols: dict = field(default_factory=dict)
    selected: set = field(default_factory=set)

    @property
    def name(self):
        return self.manifest.project

    def qualify(self, symbol):
        return f"{self.name}::{symbol}"

    def includes(self, symbol):
        return self.owned or symbol in self.selected

    @property
    def exports(self):
        return {alias: symbol for alias, symbol in getattr(self.manifest, "exports", {}).items()
                if self.includes(symbol)}

    def overrides(self, values):
        return {self.qualify(k): v for k, v in values.items() if self.includes(k)}

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
        self.modules = {}
        self.root = self.discover(project, project.manifest_path, manifest)
        self.select(project, self.root, [])
        self.select_imports(project)
        for unit in self.units.values():
            if not unit.owned:
                self.retain_visible_claims(unit)

    def discover(self, project, path, manifest=None):
        if project.allowed_manifests is not None and path not in project.allowed_manifests:
            raise ClosureError("Baseline depends on a project outside the selected assembly", "BASELINE_UNAVAILABLE", str(path))
        if path in self._paths:
            return self._paths[path]
        manifest = manifest or project._load(path, Manifest)
        project._identifier(manifest.project)
        if manifest.project in self.units:
            raise ClosureError(f"Conflicting project ID {manifest.project} at {path} and {self.units[manifest.project].path}",
                               "DUPLICATE_ID", str(path))
        unit = Unit(path, manifest)
        self.units[unit.name] = self._paths[path] = unit
        seen = set()
        for pattern in manifest.modules:
            within(path.parent, pattern)
            for source in sorted(path.parent.glob(pattern)):
                source = within(path.parent, source)
                if source in seen:
                    continue
                seen.add(source)
                module = project._load(source, Module)
                project._identifier(module.module)
                unit.modules.append((source, module))
                self.modules[unit.qualify(module.module)] = unit
                for section in (module.parameters, module.requirements):
                    unit.symbols.update({f"{module.module}.{name}": value for name, value in section.items()})
                for name, analysis in module.analyses.items():
                    unit.symbols.update({f"{module.module}.{name}.{out}": analysis for out in analysis.outputs})
        return unit

    def resolve_import(self, project, unit, alias):
        project._identifier(alias)
        link = getattr(unit.manifest, "imports", {}).get(alias)
        if link is None:
            raise ClosureError(f"Unknown import @{alias} in {unit.name}", "UNKNOWN_REF", str(unit.path))
        path = locate(unit.path, link.path, self.workspace, f"{unit.name} import @{alias} ({link.export})")
        supplier = self.discover(project, path)
        public = getattr(supplier.manifest, "exports", {})
        if link.export not in public:
            raise ClosureError(f"{unit.name} import {alias}: {supplier.name} does not export {link.export}",
                               "PRIVATE_REF", str(unit.path))
        symbol = public[link.export]
        if symbol not in supplier.symbols:
            raise ClosureError(f"Unknown export {supplier.name}.{link.export}: {symbol}",
                               "UNKNOWN_EXPORT", str(supplier.path))
        unit.imports[alias] = supplier.qualify(symbol)
        return supplier, symbol

    def select_imports(self, project):
        # Start with the imports declared by the selected project and its owned
        # children. Visit a supplier's imports only through a requested symbol.
        pending = deque((unit, "@" + alias) for unit in self.units.values()
                        for alias in getattr(unit.manifest, "imports", {}))
        while pending:
            unit, symbol = pending.popleft()
            if symbol.startswith("@"):
                alias = symbol[1:]
                if alias not in unit.imports:
                    pending.append(self.resolve_import(project, unit, alias))
                continue
            if unit.includes(symbol):
                continue
            unit.selected.add(symbol)
            contract = unit.symbols.get(symbol)
            if isinstance(contract, Analysis):
                producer = symbol.rsplit(".", 1)[0]
                unit.selected.add(producer)
                unit.selected.update(f"{producer}.{out}" for out in contract.outputs)
            elif isinstance(contract, Requirement):
                pending.extend((unit, parent) for parent in contract.derived_from)
            else:
                continue
            pending.extend((unit, b.ref) for b in contract_bindings(contract))

    @staticmethod
    def retain_visible_claims(unit):
        # Keep supplier explanations backed by the linked data without pulling
        # extra imports into the selected project's assessment.
        available = unit.selected | {"@" + alias for alias in unit.imports}
        claims = {key: claim for key, claim in unit.symbols.items() if isinstance(claim, Requirement)
                  and all(b.ref in available for b in contract_bindings(claim))}
        while True:
            visible = {key: claim for key, claim in claims.items() if all(p in claims for p in claim.derived_from)}
            if len(visible) == len(claims):
                break
            claims = visible
        unit.selected.update(claims)

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

    def module_entries(self, project):
        for unit in self.units.values():
            for path, module in unit.modules:
                if not unit.owned:
                    for section in ("parameters", "analyses", "requirements"):
                        setattr(module, section, {key: value for key, value in getattr(module, section).items()
                                                  if unit.includes(f"{module.module}.{key}")})
                    module.exports = [key for key in module.exports if unit.includes(f"{module.module}.{key}")]
                    if not (module.parameters or module.analyses or module.requirements):
                        continue
                module.module = unit.qualify(module.module)
                if not isinstance(unit.manifest, CompositionManifest):
                    for contracts in (module.analyses, module.requirements):
                        for name, contract in contracts.items():
                            project.native_contracts[f"{module.module}.{name}"] = contract.model_dump()
                for contracts in (module.analyses, module.requirements):
                    for contract in contracts.values():
                        for binding in contract_bindings(contract):
                            binding.ref = unit.reference(binding.ref)
                for requirement in module.requirements.values():
                    requirement.derived_from = [unit.qualify(ref) for ref in requirement.derived_from]
                yield path, module

    def scope(self, requirements):
        result = []
        for unit in self.units.values():
            if not unit.owned:
                continue
            result.extend(self.local_scope(unit, requirements))
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
        applicable_by_project = {}

        def evaluate(unit):
            if unit.name in applicable_by_project:
                return applicable_by_project[unit.name]
            scoped = self.local_scope(unit, requirements)
            applicable = {key for key in scoped if indexed[key]["applicability"] == "applicable"}
            reasons = [key for key in scoped if not indexed[key]["gate_allowed"]]
            for child in dict.fromkeys(unit.children.values()):
                applicable.update(evaluate(self.units[child]))
                if not gates[child]["gate"]:
                    reasons.append(child)
            if baselines[unit.name]["status"] != "current":
                reasons.append("Obligation baseline " + baselines[unit.name]["status"])
            if not applicable:
                reasons.append("No applicable obligations")
            gates[unit.name] = {"project": unit.name, "gate": not reasons, "applicable": len(applicable),
                                "scope": scoped, "reasons": reasons}
            applicable_by_project[unit.name] = applicable
            return applicable

        evaluate(self.root)
        return gates

    def describe(self):
        return {unit.name: {"name": unit.manifest.name or unit.name, "source": unit.path.relative_to(self.workspace).as_posix(),
                            "owned": unit.owned, "children": unit.children, "imports": unit.imports,
                            "exports": unit.exports, "scope": unit.manifest.scope,
                            "excluded_children": [key for key, link in getattr(unit.manifest, "children", {}).items() if not link.required],
                            "policy": unit.manifest.policy.model_dump()}
                for unit in self.units.values()}

