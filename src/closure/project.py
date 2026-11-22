from __future__ import annotations

from .composition import Composition, manifest_path, workspace_root
import graphlib
import re
from pathlib import Path
from pydantic import ValidationError
from .io import ClosureError, load_source, digest, file_digest, primitive, within
from .models import CompositionManifest, Manifest, Module, Datum, Binding, Criterion
from .units import compatible, convert


def criteria(verification):
    if verification is None:
        return []
    if isinstance(verification, Criterion):
        return [verification]
    return verification.all_of or verification.any_of


def refs(criterion):
    return [criterion.actual] + ([criterion.limit] if isinstance(criterion.limit, Binding) else [])


def source_location(document, section, key, path):
    try:
        return f"{path}:{document[section].lc.key(key)[0] + 1}"
    except (AttributeError, KeyError, TypeError):
        return f"{path}:1"


class Project:
    def __init__(self, path: str | Path, workspace=None):
        self.manifest_path = manifest_path(path)
        self.root = self.manifest_path.parent
        self.boundary = Path(workspace).resolve() if workspace else None
        if self.boundary and not self.manifest_path.is_relative_to(self.boundary):
            raise ClosureError("Selected project escapes workspace", "PATH_ESCAPE")
        self.workspace = workspace_root(self.manifest_path, self.boundary)
        self.document_hashes = {}
        self.locations = {}
        self.documents = {}
        self.modules = {}
        self.parameters = {}
        self.analyses = {}
        self.requirements = {}
        self.ports = {}
        self.producers = {}
        self.edges = []
        self.source_files = []
        self.manifest = self._load(self.manifest_path, Manifest)
        self.composition = (Composition(self, self.manifest, self.workspace)
                            if isinstance(self.manifest, CompositionManifest) else None)
        entries = self.composition.module_entries() if self.composition else self._local_modules()
        for module_path, module in entries:
            if module.module in self.modules:
                raise ClosureError(f"Duplicate module {module.module}", "DUPLICATE_ID", str(module_path))
            self.modules[module.module] = module
            self.locations[module.module] = str(module_path)
            for section, target in [("parameters", self.parameters), ("analyses", self.analyses), ("requirements", self.requirements)]:
                for local, value in getattr(module, section).items():
                    self._identifier(local)
                    qualified = f"{module.module}.{local}"
                    if qualified in self.locations:
                        raise ClosureError(f"Duplicate symbol {qualified}", "DUPLICATE_ID")
                    target[qualified] = value
                    self.locations[qualified] = source_location(self.documents[module_path], section, local, module_path)
                    self.edges.append({"source": module.module, "target": qualified, "kind": "contains"})
        if not self.modules:
            raise ClosureError("No module files matched", "EMPTY_PROJECT", str(self.manifest_path))
        for identifier, datum in self.parameters.items():
            self.ports[identifier] = datum.port()
        for identifier, analysis in self.analyses.items():
            for name, port in analysis.outputs.items():
                self._identifier(name)
                output = f"{identifier}.{name}"
                if output in self.ports:
                    raise ClosureError(f"Multiple producers for {output}", "AMBIGUOUS_PRODUCER")
                self.ports[output] = port
                self.producers[output] = identifier
                self.edges.append({"source": identifier, "target": output, "kind": "produces"})
        self.dependencies = {identifier: set() for identifier in self.analyses}
        self._link()
        try:
            self.order = list(graphlib.TopologicalSorter(self.dependencies).static_order())
        except graphlib.CycleError as exc:
            cycle = exc.args[1]
            raise ClosureError("Computational cycle: " + " -> ".join(cycle), "COMPUTE_CYCLE", self.locations[cycle[0]]) from exc
        self.scope = sorted(k for k, v in self.requirements.items() if v.required) if self.manifest.scope == ["*"] else self.manifest.scope
        if self.composition:
            self.scope = self.composition.scope(self.requirements)
            for unit in self.composition.units.values():
                for public, symbol in getattr(unit.manifest, "exports", {}).items():
                    target = unit.qualify(symbol)
                    if target not in self.ports and target not in self.requirements:
                        raise ClosureError(f"Unknown export {unit.name}.{public}: {symbol}", "UNKNOWN_EXPORT", str(unit.path))
                for alias, link in getattr(unit.manifest, "imports", {}).items():
                    if link.port is None:
                        continue
                    target = unit.imports[alias]
                    port = self.ports.get(target)
                    if port is None or port.type != link.port.type or (port.type == "enum" and port.choices != link.port.choices):
                        raise ClosureError(f"{unit.name}.{alias}: {target} has incompatible type", "TYPE_MISMATCH", str(unit.path))
                    try:
                        compatible(port, link.port.unit, link.port.qualifiers)
                    except ClosureError as exc:
                        raise ClosureError(f"{unit.name}.{alias} -> {target}: {exc}", exc.code, str(unit.path)) from exc
        for identifier in self.scope:
            if identifier not in self.requirements:
                raise ClosureError(f"Unknown scoped requirement {identifier}", "UNKNOWN_REF")
        if self.composition:
            # Schedule only producers reachable from selected obligations.
            pending = [self.producers[b.ref] for key in self.scope
                       for condition in criteria(self.requirements[key].verify)
                       for b in refs(condition) if b.ref in self.producers]
            needed = set()
            while pending:
                analysis = pending.pop()
                if analysis not in needed:
                    needed.add(analysis)
                    pending.extend(self.dependencies[analysis])
            self.order = [key for key in self.order if key in needed]
        origin = self.workspace if self.composition else self.root
        self.source_hash = digest({str(p.relative_to(origin)): value for p, value in self.document_hashes.items()})

    def _local_modules(self):
        for pattern in self.manifest.modules:
            within(self.root, pattern)
            for path in sorted(self.root.glob(pattern)):
                path = within(self.root, path)
                if path not in self.source_files:
                    module = self._load(path, Module)
                    self._identifier(module.module)
                    yield path, module

    def unit_for(self, identifier):
        return self.composition.modules[identifier.split(".")[0]] if self.composition else None

    def source_root(self, identifier):
        unit = self.unit_for(identifier)
        return unit.path.parent if unit else self.root

    @staticmethod
    def _identifier(value):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value):
            raise ClosureError(f"Invalid symbol {value!r}", "INVALID_ID")

    def model_snapshot(self):
        """Normalized contracts and links for displaying an assessment after edits."""
        return {"project": self.manifest.model_dump(mode="json", by_alias=True),
                "modules": [module.model_dump(mode="json", by_alias=True) for module in self.modules.values()],
                "edges": self.edges, "protected_parameters": sorted(self.protected_parameters())}

    def _load(self, path, model):
        before = file_digest(path) if path.is_file() else None
        document = load_source(path)
        if before != file_digest(path):
            raise ClosureError("Definition changed during loading", "SOURCE_CONFLICT", str(path))
        self.document_hashes[path] = before
        if model is Manifest and document.get("schema") == "closure/0.2":
            model = CompositionManifest
        try:
            result = model.model_validate(primitive(document))
        except ValidationError as exc:
            raise ClosureError(str(exc), "SCHEMA", str(path)) from exc
        self.documents[path] = document
        self.source_files.append(path)
        return result

    def _binding(self, binding, consumer):
        if binding.ref not in self.ports:
            raise ClosureError(f"Unknown reference {binding.ref} in {consumer}", "UNKNOWN_REF", self.locations[consumer])
        supplier = binding.ref.split(".")[0]
        if consumer.split(".")[0] != supplier:
            local = binding.ref[len(supplier) + 1:]
            external = self.composition and self.unit_for(consumer) is not self.unit_for(binding.ref)
            if not external and local not in self.modules[supplier].exports:
                raise ClosureError(f"{binding.ref} is private; add it to exports", "PRIVATE_REF", self.locations[consumer])
        try:
            compatible(self.ports[binding.ref], binding.unit, binding.qualifiers)
        except ClosureError as exc:
            exc.location = self.locations[consumer]
            raise
        return self.ports[binding.ref]

    def _criterion(self, criterion, consumer):
        actual = self._binding(criterion.actual, consumer)
        limit = self._binding(criterion.limit, consumer) if isinstance(criterion.limit, Binding) else criterion.limit.port()
        if actual.type == "artifact" or limit.type == "artifact":
            raise ClosureError("Compare artifacts in an analysis that produces a scalar or boolean result", "TYPE_MISMATCH", self.locations[consumer])
        if actual.type != limit.type and {actual.type, limit.type} != {"enum", "string"}:
            raise ClosureError(f"Criterion types differ in {consumer}", "TYPE_MISMATCH", self.locations[consumer])
        if actual.type == "quantity":
            convert(1, limit.unit, actual.unit)
        if actual.qualifiers != limit.qualifiers:
            raise ClosureError(f"Criterion semantic qualifiers differ in {consumer}", "QUALIFIER_MISMATCH", self.locations[consumer])
        if actual.type not in ("quantity", "scalar") and criterion.op not in ("eq", "ne"):
            raise ClosureError("Ordered comparisons require numbers", "TYPE_MISMATCH", self.locations[consumer])

    def _link(self):
        for module in self.modules.values():
            for export in module.exports:
                if f"{module.module}.{export}" not in self.ports:
                    raise ClosureError(f"Unknown export {module.module}.{export}", "UNKNOWN_EXPORT")
        for identifier, analysis in self.analyses.items():
            bindings = list(analysis.inputs.values())
            for condition in analysis.valid_when:
                self._criterion(condition, identifier)
                bindings.extend(refs(condition))
            for binding in bindings:
                self._binding(binding, identifier)
                self.edges.append({"source": binding.ref, "target": identifier, "kind": "consumes"})
                if binding.ref in self.producers:
                    self.dependencies[identifier].add(self.producers[binding.ref])
            for source in analysis.run.sources:
                within(self.source_root(identifier), source)
            if analysis.run.environment_lock:
                lock = within(self.source_root(identifier), analysis.run.environment_lock)
                if not lock.is_file():
                    raise ClosureError(f"Missing environment lock {lock}", "MISSING_SOURCE", self.locations[identifier])
        for identifier, requirement in self.requirements.items():
            for condition in criteria(requirement.verify):
                self._criterion(condition, identifier)
                for binding in refs(condition):
                    self.edges.append({"source": binding.ref, "target": identifier, "kind": "verifies"})
            for parent in requirement.derived_from:
                if parent not in self.requirements:
                    raise ClosureError(f"Unknown parent {parent}", "UNKNOWN_REF")
                self.edges.append({"source": identifier, "target": parent, "kind": "derived_from"})
            if not requirement.applies_to or not requirement.configurations:
                raise ClosureError(f"Empty applicability for {identifier}", "EMPTY_APPLICABILITY")
            owner = self.unit_for(identifier).manifest if self.composition else self.manifest
            if set(requirement.applies_to) - set(owner.scenarios) or set(requirement.configurations) - set(owner.configurations):
                raise ClosureError(f"Unknown requirement context for {identifier}", "UNKNOWN_CONTEXT")
        owners = self.composition.units.values() if self.composition else [None]
        for unit in owners:
            manifest = unit.manifest if unit else self.manifest
            for groups in (manifest.scenarios, manifest.configurations):
                for context in groups.values():
                    self.resolve_parameters({unit.qualify(k) if unit else k: v for k, v in context.overrides.items()})

    def resolve_parameters(self, overrides=None):
        values = dict(self.parameters)
        for identifier, override in (overrides or {}).items():
            if identifier not in self.parameters:
                raise ClosureError(f"Override targets unknown input {identifier}", "UNKNOWN_REF")
            if not isinstance(override, Datum):
                override = Datum.model_validate(override)
            original = self.parameters[identifier]
            replacement = Datum.model_validate({**original.model_dump(), **override.model_dump(exclude_unset=True)})
            if replacement.type != original.type or replacement.qualifiers != original.qualifiers:
                raise ClosureError(f"Override changes type/meaning of {identifier}", "TYPE_MISMATCH")
            if original.unit:
                convert(replacement.value, replacement.unit, original.unit)
            values[identifier] = replacement
        return values

    def obligation_contract(self):
        protected = self.protected_parameters()
        if self.composition:
            included = set(self.scope)
            units = self.composition.describe()
            return {"scope": self.scope, "projects": units,
                    "requirements": {k: self.requirements[k].model_dump() for k in sorted(included)},
                    "limit_inputs": {k: self.parameters[k].model_dump() for k in sorted(protected)},
                    "contexts": {u.name: {group: {name: {k: v.model_dump() for k, v in context.overrides.items()
                                                          if u.qualify(k) in protected}
                                                   for name, context in getattr(u.manifest, group).items()}
                                          for group in ("scenarios", "configurations")}
                                 for u in self.composition.units.values()}}
        return {"requirements": {k: v.model_dump() for k, v in self.requirements.items()}, "scope": self.scope,
                "scenarios": sorted(self.manifest.scenarios), "configurations": sorted(self.manifest.configurations),
                "policy": self.manifest.policy.model_dump(),
                "limit_inputs": {k: self.parameters[k].model_dump() for k in sorted(protected)},
                "context_limit_overrides": {group: {name: {k: v.model_dump() for k, v in context.overrides.items() if k in protected}
                                                    for name, context in contexts.items()}
                                            for group, contexts in [("scenarios", self.manifest.scenarios), ("configurations", self.manifest.configurations)]}}

    def protected_parameters(self):
        pending = [condition.limit.ref for requirement in self.requirements.values()
                   for condition in criteria(requirement.verify) if isinstance(condition.limit, Binding)]
        visited, protected = set(), set()
        while pending:
            identifier = pending.pop()
            if identifier in visited:
                continue
            visited.add(identifier)
            if identifier in self.parameters:
                protected.add(identifier)
            elif identifier in self.producers:
                analysis = self.analyses[self.producers[identifier]]
                pending.extend(binding.ref for binding in analysis.inputs.values())
        return protected

    def check(self):
        diagnostics = []
        if not self.scope or not self.manifest.scenarios or not self.manifest.configurations:
            diagnostics.append({"code": "EMPTY_SCOPE", "message": "Required scope and contexts must be nonempty", "location": str(self.manifest_path)})
        if self.composition:
            for unit in self.composition.units.values():
                for names in ("scenarios", "configurations"):
                    missing = set(getattr(self.manifest, names)) - set(getattr(unit.manifest, names))
                    if missing:
                        diagnostics.append({"code": "UNKNOWN_CONTEXT", "location": str(unit.path),
                                            "message": f"{unit.name} lacks {names}: {', '.join(sorted(missing))}"})
        for identifier, requirement in self.requirements.items():
            if requirement.verify is None:
                diagnostics.append({"code": "OPEN_OBLIGATION", "message": f"{identifier} has no verification evidence binding", "severity": "warning", "location": self.locations[identifier]})
        return {"valid": not any(d.get("severity") != "warning" for d in diagnostics), "project": self.manifest.project,
                "source_hash": self.source_hash, "diagnostics": diagnostics, "analyses": self.order, "requirements": len(self.requirements)}

    def impact(self, identifier):
        if identifier not in self.locations and identifier not in self.ports:
            raise ClosureError(f"Unknown symbol {identifier}", "UNKNOWN_REF")
        seen, pending = {identifier}, [identifier]
        while pending:
            current = pending.pop()
            for edge in self.edges:
                if edge["source"] == current and edge["kind"] in ("consumes", "produces", "verifies") and edge["target"] not in seen:
                    seen.add(edge["target"])
                    pending.append(edge["target"])
        return {"changed": identifier, "affected": sorted(seen - {identifier}), "requirements": sorted(seen & self.requirements.keys())}
