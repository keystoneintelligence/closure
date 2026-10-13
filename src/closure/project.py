from __future__ import annotations

import graphlib
import re
from pathlib import Path
from pydantic import ValidationError
from .io import ClosureError, load_source, digest, file_digest, primitive, within
from .models import Manifest, Module, Datum, Binding, Criterion
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
    def __init__(self, path: str | Path):
        path = Path(path).resolve()
        self.root = path if path.is_dir() else path.parent
        if path.is_dir():
            manifests = [path / name for name in ("project.yaml", "project.yml", "project.json") if (path / name).is_file()]
            if len(manifests) > 1:
                raise ClosureError("Multiple project manifests; select one explicitly", "AMBIGUOUS_MANIFEST", str(path))
            self.manifest_path = manifests[0] if manifests else path / "project.yaml"
        else:
            self.manifest_path = path
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
        for pattern in self.manifest.modules:
            within(self.root, pattern)
            for module_path in sorted(self.root.glob(pattern)):
                if module_path in self.source_files:
                    continue
                module = self._load(module_path, Module)
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
                self._identifier(module.module)
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
        for identifier in self.scope:
            if identifier not in self.requirements:
                raise ClosureError(f"Unknown scoped requirement {identifier}", "UNKNOWN_REF")
        self.source_hash = digest({str(p.relative_to(self.root)): file_digest(p) for p in self.source_files})

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
        document = load_source(path)
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
            if local not in self.modules[supplier].exports:
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
                within(self.root, source)
            if analysis.run.environment_lock:
                lock = within(self.root, analysis.run.environment_lock)
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
            if set(requirement.applies_to) - set(self.manifest.scenarios) or set(requirement.configurations) - set(self.manifest.configurations):
                raise ClosureError(f"Unknown requirement context for {identifier}", "UNKNOWN_CONTEXT")
        for contexts in [self.manifest.scenarios, self.manifest.configurations]:
            for context in contexts.values():
                self.resolve_parameters(context.overrides)

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
