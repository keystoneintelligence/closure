"""Plan, execute, assess, and explain a selected engineering context."""
from __future__ import annotations

import fnmatch
import itertools
import operator
import errno
import time
import uuid
from contextlib import ExitStack
from pathlib import Path
from . import __version__
from .assessment_history import compare_reports, contract_changes, previous_report, revision
from .evidence import EvidenceStore, environment_identity, limit_tools, resolve_executable, source_snapshot, tool_identity, utcnow
from .io import ClosureError, atomic_json, digest, file_digest, load_source, read_json, within
from .models import Binding, Criterion, Datum, Study
from .protocol import validate_report, StudyResult
from .project import Project, criteria, refs
from .units import convert
from .editing import project_lock

OPS = {"lte": operator.le, "gte": operator.ge, "lt": operator.lt, "gt": operator.gt, "eq": operator.eq, "ne": operator.ne}


class Engine:
    def __init__(self, project: Project | str | Path, scenario=None, configuration=None, overrides=None, point="baseline"):
        self.project = project if isinstance(project, Project) else Project(project)
        self.store = EvidenceStore(self.project.root)
        stores = {self.project.root: self.store}
        self.owner_stores = {}
        for key in self.project.order:
            root = self.project.source_root(key)
            if root not in stores:
                stores[root] = EvidenceStore(root)
            self.owner_stores[key] = stores[root]
        self.run_stores = dict(self.owner_stores)
        self.record_stores = {}
        self.owner_versions = {}
        manifest = self.project.manifest
        scenario = scenario if scenario is not None else next(iter(manifest.scenarios), None)
        configuration = configuration if configuration is not None else next(iter(manifest.configurations), None)
        self.context = {"scenario": scenario, "configuration": configuration, "point": point}
        if scenario not in manifest.scenarios or configuration not in manifest.configurations:
            raise ClosureError("Selected scenario/configuration is not declared", "UNKNOWN_CONTEXT")
        if set(overrides or {}) & self.project.protected_parameters():
            raise ClosureError("Study or ad hoc overrides cannot alter inputs that define requirement limits; propose and review an obligation change", "OBLIGATION_CHANGE")
        combined = {**manifest.configurations[configuration].overrides, **manifest.scenarios[scenario].overrides, **(overrides or {})}
        if self.project.composition:
            combined = {}
            for unit in self.project.composition.units.values():
                if scenario not in unit.manifest.scenarios or configuration not in unit.manifest.configurations:
                    raise ClosureError(f"{unit.name} does not declare {scenario} / {configuration}",
                                       "UNKNOWN_CONTEXT", str(unit.path))
                local = {**unit.manifest.configurations[configuration].overrides,
                         **unit.manifest.scenarios[scenario].overrides}
                combined.update({unit.qualify(k): v for k, v in local.items()})
            combined.update(overrides or {})
        self.parameters = self.project.resolve_parameters(combined)
        self.environment = environment_identity()
        self.states, self.records, self.keys, self.sources, self.values = {}, {}, {}, {}, {}
        self.tools = {}
        self.failures = {}
        self.executed = []
        self.pinned_sources = None
        self.revision = None
        for identifier, datum in self.parameters.items():
            if datum.type == "artifact":
                artifact = within(self.project.source_root(identifier), datum.path)
                if artifact.is_file() and self.project.composition:
                    with artifact.open("rb") as source:
                        if source.readline(128).rstrip() == b"version https://git-lfs.github.com/spec/v1":
                            raise ClosureError(f"Materialize the Git LFS input for {identifier}", "MISSING_INPUT", str(artifact))
                if artifact.is_file():
                    self.values[identifier] = {"type": "artifact", "path": str(artifact), "sha256": file_digest(artifact), "name": artifact.name,
                                               "qualifiers": datum.qualifiers}
            else:
                self.values[identifier] = {"value": datum.value, "unit": datum.unit, "type": datum.type, "qualifiers": datum.qualifiers}

    def _slot(self, identifier):
        return digest({"analysis": self.project.evidence_id(identifier), "context": self.context})

    def _binding_value(self, binding):
        value = dict(self.values[binding.ref])
        if binding.unit:
            value["value"] = convert(value["value"], value["unit"], binding.unit)
            value["unit"] = binding.unit
        return value

    def _criterion(self, criterion):
        try:
            actual = self._binding_value(criterion.actual)
            limit = self._binding_value(criterion.limit) if isinstance(criterion.limit, Binding) else {"value": criterion.limit.value, "unit": criterion.limit.unit}
        except KeyError:
            return {"verdict": "unknown", "actual": None, "limit": None, "margin": None, "ref": criterion.actual.ref}
        left, right = actual.get("value"), limit.get("value")
        if actual.get("unit"):
            right = convert(right, limit["unit"], actual["unit"])
        passed = OPS[criterion.op](left, right)
        margin = None
        if criterion.op in ("lte", "lt"):
            margin = right - left
        elif criterion.op in ("gte", "gt"):
            margin = left - right
        return {"verdict": "pass" if passed else "fail", "actual": left, "limit": right, "margin": margin,
                "unit": actual.get("unit"), "op": criterion.op, "ref": criterion.actual.ref, "description": criterion.description}

    def _prepare(self, identifier):
        analysis = self.project.analyses[identifier]
        self.records.pop(identifier, None)
        self.record_stores.pop(identifier, None)
        self.failures.pop(identifier, None)
        for name in analysis.outputs:
            self.values.pop(f"{identifier}.{name}", None)
        self.sources[identifier] = source_snapshot(self.project, analysis, self.project.source_root(identifier))
        if self.pinned_sources is not None and self.sources[identifier] != self.pinned_sources[identifier]:
            raise ClosureError("Analysis sources changed during verification", "SOURCE_CONFLICT", identifier)
        identities = {}
        bindings = list(analysis.inputs.values()) + [ref for c in analysis.valid_when for ref in refs(c)]
        for binding in bindings:
            name = self.project.evidence_id(binding.ref, identifier)
            if binding.ref in self.parameters:
                parameter = self.parameters[binding.ref]
                resolved = self.values.get(binding.ref)
                if resolved and parameter.type == "artifact":
                    # The runner consumes staged bytes under their original name.
                    resolved = {field: value for field, value in resolved.items() if field != "path"}
                identities[name] = {"source": parameter.model_dump(), "resolved": resolved}
            else:
                producer = self.project.producers[binding.ref]
                identities[name] = {"producer": self.keys.get(producer), "run": self.records.get(producer, {}).get("record_hash")}
        executable = resolve_executable(analysis.run.argv)[0]
        self.tools[identifier] = tool_identity(analysis.run, self.project.source_root(identifier))
        native_id = self.project.evidence_id(identifier)
        unit = self.project.unit_for(identifier)
        identity = {"protocol": "closure-run/0.1", "engine": __version__, "analysis": native_id,
                    "project": unit.name if unit else self.project.manifest.project,
                    "contract": self.project.native_contracts.get(identifier, analysis.model_dump()), "sources": self.sources[identifier], "environment": self.environment,
                    "executable": {"path": executable, "sha256": file_digest(executable)}, "tools": self.tools[identifier], "inputs": identities, "context": self.context}
        self.keys[identifier] = digest(identity)
        key, slot = self.keys[identifier], self._slot(identifier)
        store = self.owner_stores[identifier]
        if store.root != self.store.root:
            # A read-only mount may only reveal its permissions when the first write fails.
            # A locally retained run stays active until the owner publishes or withdraws its run.
            owner_version = {"source": store.root.parent.relative_to(self.project.workspace).as_posix(),
                             "run": store.active_version(key)}
            self.owner_versions[identifier] = owner_version
            if self.store.index().get("local_fallbacks", {}).get(key) == owner_version:
                store = self.store
        state, record = store.lookup(key, slot)
        if analysis.run.uncontrolled_dependencies or (analysis.run.stochastic and analysis.run.seed is None):
            state, record = "stale" if state == "current" else state, None
        blocked = any(self.states.get(dependency) != "current" for dependency in self.project.dependencies[identifier])
        if blocked:
            state, record = "stale" if state == "current" else state, None
        self.states[identifier] = state
        if record:
            if record["context"] != self.context or record["analysis"] != native_id:
                self.states[identifier] = "missing"
            else:
                self._use_record(identifier, record, store)

    def _use_record(self, identifier, record, store):
        self.records[identifier] = record
        self.record_stores[identifier] = store
        self.states[identifier] = "current"
        for name, value in record["outputs"].items():
            if value.get("type") == "artifact":
                value = {**value, "path": str(store.artifact_path(value))}
            self.values[f"{identifier}.{name}"] = value

    def plan(self):
        self.executed = []
        for identifier in self.project.order:
            try:
                self._prepare(identifier)
            except ClosureError as exc:
                self.states[identifier] = "missing"
                self.failures[identifier] = exc.as_dict()
        return self.report()

    def verify(self, trusted=False, force=False, progress=None):
        """Refresh affected evidence, or rerun every analysis when force is set."""
        return self.build(trusted=trusted, force=force, progress=progress)

    def build(self, trusted=False, force=False, progress=None):
        if not trusted:
            raise ClosureError("Execution requires explicit trusted=True or --trusted", "TRUST_REQUIRED")
        self.run_stores = dict(self.owner_stores)
        with ExitStack() as locks:
            self.owner_versions = {}
            roots = {self.project.root, *(store.root.parent for store in self.run_stores.values())}
            for root in sorted(roots):
                try:
                    locks.enter_context(project_lock(root))
                except OSError as exc:
                    if root == self.project.root or exc.errno not in (errno.EACCES, errno.EPERM, errno.EROFS):
                        raise
                    for key, store in self.run_stores.items():
                        if store.root.parent == root:
                            self.run_stores[key] = self.store
            if Project(self.project.manifest_path, self.project.boundary).source_hash != self.project.source_hash:
                raise ClosureError("Project source changed after this engine was prepared", "SOURCE_CONFLICT")
            if self.project.composition:
                self.pinned_sources, self.input_files = self.invocation_inputs()
                self.revision = revision(self.project.workspace, self.input_files)
            return self._build(force=force, progress=progress)

    def invocation_inputs(self):
        files = dict(self.project.document_hashes)
        sources = {}
        _, limit_producers = self.project.limit_dependencies()
        for key in self.project.order:
            root = self.project.source_root(key)
            try:
                sources[key] = source_snapshot(self.project, self.project.analyses[key], root)
            except ClosureError:
                sources[key] = None  # The planner reports the specific missing input.
            if key in limit_producers:
                try:
                    for path in limit_tools(self.project.analyses[key].run).values():
                        files[path] = file_digest(path)
                except ClosureError:
                    pass  # Preparation reports the unavailable tool as missing evidence.
            files.update({root / path: value for path, value in (sources[key] or {}).items()})
            for path in self.project.analyses[key].run.tool_files:
                target = (root / path).resolve()
                files[target] = file_digest(target) if target.is_file() else None
        for key, parameter in self.parameters.items():
            if parameter.type == "artifact":
                path = within(self.project.source_root(key), parameter.path)
                checksum = file_digest(path) if path.is_file() else None
                if checksum != self.values.get(key, {}).get("sha256"):
                    raise ClosureError(f"Input changed since loading: {key}", "SOURCE_CONFLICT")
                files[path] = checksum
        for unit in self.project.composition.units.values():
            root = unit.path.parent
            review_files = [within(root, unit.manifest.baseline)]
            for pattern in unit.manifest.reviews:
                within(root, pattern)
                review_files.extend(within(root, p) for p in root.glob(pattern))
            for path in review_files:
                files[path] = file_digest(path) if path.is_file() else None
        return sources, files

    def _build(self, force=False, progress=None):
        self.executed = []
        def notify(event, **details):
            if progress:
                progress({"event": event, "analysis": identifier, "index": index,
                          "total": len(self.project.order), "context": dict(self.context), **details})

        for index, identifier in enumerate(self.project.order, 1):
            analysis = self.project.analyses[identifier]
            started = time.monotonic()
            try:
                self._prepare(identifier)
                if self.states[identifier] == "current" and not force:
                    notify("cached")
                    continue
                store = self.run_stores[identifier]
                if store.root != self.owner_stores[identifier].root:
                    store.invalidate(self.keys[identifier], fallback_for=self.owner_versions[identifier])
                elif force:
                    if self.record_stores.get(identifier) is self.store and store is not self.store:
                        self.store.invalidate(self.keys[identifier])
                    store.invalidate(self.keys[identifier])
                if force:
                    # A failed forced rerun cannot leave an old passing record
                    # available to dependent analyses or requirement assessment.
                    self.records.pop(identifier, None)
                    for name in analysis.outputs:
                        self.values.pop(f"{identifier}.{name}", None)
                    self.states[identifier] = "stale"
                if any(self.states.get(dependency) != "current" for dependency in self.project.dependencies[identifier]):
                    raise ClosureError("An upstream analysis has no current evidence", "BLOCKED")
                if any(self._criterion(c)["verdict"] != "pass" for c in analysis.valid_when):
                    raise ClosureError("Analysis validity conditions are not satisfied", "INVALID_DOMAIN")
                try:
                    inputs = {name: self._binding_value(binding) for name, binding in analysis.inputs.items()}
                except KeyError as exc:
                    raise ClosureError(f"Missing input artifact/value {exc}", "MISSING_INPUT") from exc
                notify("running", reason="forced" if force else self.states[identifier])
                record = store.execute(self.project, identifier, analysis, self.keys[identifier], self._slot(identifier),
                                            self.context, inputs, self.sources[identifier], self.environment,
                                            {self.project.evidence_id(dep, identifier): self.records[dep]["record_hash"] for dep in sorted(self.project.dependencies[identifier])}, self.tools[identifier])
                self._use_record(identifier, record, store)
                self.executed.append(identifier)
                notify("completed", seconds=time.monotonic() - started)
            except ClosureError as exc:
                self.failures[identifier] = exc.as_dict()
                self.states[identifier] = "blocked" if exc.code in ("BLOCKED", "INVALID_DOMAIN", "MISSING_INPUT") else "error"
                notify(self.states[identifier], error=exc.as_dict())
        report = self.report()
        if self.project.composition:
            for key, version in self.owner_versions.items():
                owner = self.owner_stores[key]
                if self.run_stores[key].root != owner.root and owner.active_version(self.keys[key]) != version["run"]:
                    raise ClosureError("Owner evidence changed during verification; retry", "SOURCE_CONFLICT", key)
            current = Project(self.project.manifest_path, self.project.boundary)
            if (current.source_hash != self.project.source_hash or self.invocation_inputs() != (self.pinned_sources, self.input_files)
                    or revision(self.project.workspace, self.input_files) != self.revision):
                raise ClosureError("Inputs or revision changed during verification; retry", "SOURCE_CONFLICT")
            report["revision"] = self.revision
            report["comparison"] = compare_reports(previous_report(self.store, report), report)
        for key, record in self.records.items():
            source = self.record_stores[key]
            if source.root != self.store.root:
                self.store.retain_run(record, source)
        return self.store.save_report(report)

    def baseline(self, project=None):
        project = project or self.project
        path = within(project.root, project.manifest.baseline)
        contract = project.obligation_contract()
        current = digest(contract)
        if not path.exists():
            return {"status": "missing", "current_hash": current, "message": "Initial obligations need a recorded baseline review."}
        approved = read_json(path)
        valid = approved.get("contract_hash") == current and bool(approved.get("reviewer")) and digest(approved.get("contract")) == current
        message = "Obligations match the reviewed baseline."
        if not valid:
            message = "Acceptance definitions changed. A separate baseline review is required."
            previous = approved.get("contract", {})
            for field in ("limit_calculations", "limit_artifacts"):
                if previous.get(field) != contract.get(field):
                    message += " " + " ".join(contract_changes(previous.get(field), contract.get(field), field))
        return {"status": "current" if valid else "changed", "current_hash": current,
                "approved_hash": approved.get("contract_hash"), "reviewer": approved.get("reviewer"),
                "message": message}

    def _reviews(self, project=None):
        project = project or self.project
        reviews = []
        for pattern in project.manifest.reviews:
            within(project.root, pattern)
            for path in project.root.glob(pattern):
                review = read_json(path)
                if review.get("reviewer") and review.get("reason"):
                    reviews.append(review)
        return sorted(reviews, key=lambda r: r.get("at", ""))

    def _criterion_support(self, criterion, index, policy):
        sources = [binding.ref for binding in refs(criterion)]
        producers = sorted({self.project.producers[ref] for ref in sources if ref in self.project.producers})
        states = [self.states.get(p, "missing") for p in producers]
        missing_inputs = any(ref in self.parameters and ref not in self.values for ref in sources)
        freshness = "current" if not missing_inputs and all(s == "current" for s in states) else "stale" if "stale" in states else "missing"
        execution = "error" if "error" in states else "blocked" if "blocked" in states else "complete" if freshness == "current" else "not_run"
        classes = {self.records[p]["evidence_class"] for p in producers if p in self.records}
        for ref in sources:
            if ref in self.parameters:
                origin = self.parameters[ref].origin
                classes.add("assumed" if origin in ("assumption", "design") else origin)
        comparison = self._criterion(criterion) if freshness == "current" else None
        return {"index": index, "ref": criterion.actual.ref, "freshness": freshness, "execution": execution,
                "verdict": comparison["verdict"] if comparison else "unknown", "comparison": comparison,
                "dependencies": producers, "evidence": [self.records[p]["id"] for p in producers if p in self.records],
                "evidence_classes": sorted(classes),
                "evidence_allowed": classes.issubset(policy.accepted_evidence)}

    def assess(self, identifier, baseline, reviews, linked_reviews=()):
        requirement = self.project.requirements[identifier]
        applicable = self.context["scenario"] in requirement.applies_to and self.context["configuration"] in requirement.configurations
        conditions = criteria(requirement.verify)
        sources = [binding.ref for c in conditions for binding in refs(c)]
        producers = sorted({self.project.producers[ref] for ref in sources if ref in self.project.producers})
        alternative = bool(conditions) and not isinstance(requirement.verify, Criterion) and requirement.verify.any_of is not None
        policy = self.project.policy_for(identifier)
        branches = [self._criterion_support(c, i, policy) for i, c in enumerate(conditions)]
        # A declared alternative needs one current passing branch. Prefer evidence
        # allowed by policy; unused alternatives must not veto its closure.
        passing = [b for b in branches if b["verdict"] == "pass" and b["execution"] == "complete"]
        preferred = [b for b in passing if b["evidence_allowed"]] or passing
        support = preferred[:1] if alternative and preferred else branches
        selected = [b["index"] for b in support] if support and (not alternative or preferred) else []
        freshness = "current" if support and all(b["freshness"] == "current" for b in support) else "stale" if any(b["freshness"] == "stale" for b in support) else "missing"
        executions = [b["execution"] for b in support]
        execution = "error" if "error" in executions else "blocked" if "blocked" in executions else "complete" if freshness == "current" else "not_run"
        outcomes = [b["verdict"] for b in support]
        verdict = "unknown"
        if outcomes and freshness == "current":
            verdict = ("pass" if "pass" in outcomes else "unknown" if "unknown" in outcomes else "fail") if alternative else ("fail" if "fail" in outcomes else "unknown" if "unknown" in outcomes else "pass")
        comparisons = [{**b["comparison"], "branch": b["index"]} for b in branches if b["comparison"]]
        classes = {c for b in support for c in b["evidence_classes"]}
        support_identity = {"requirement": self.project.native_contracts.get(identifier, requirement.model_dump()),
                            "context": self.context,
                            "records": {self.project.evidence_id(p, identifier): self.records.get(p, {}).get("record_hash") for p in producers},
                            "inputs": {self.project.evidence_id(r, identifier): self.parameters[r].model_dump() for r in sources if r in self.parameters}}
        if alternative:
            support_identity["selected_branches"] = selected

        def review_signature(assessment_policy):
            terms = assessment_policy.model_dump()
            terms["accepted_evidence"] = sorted(terms["accepted_evidence"])
            return digest({**support_identity, "policy": terms})

        signature = review_signature(policy)
        decisions = {}
        candidates = [(self.project.manifest.project, signature, r) for r in reviews if r.get("requirement") == identifier]
        candidates.extend((authority, review_signature(terms), r) for authority, terms, r in linked_reviews)
        for authority, expected, entry in candidates:
            if entry.get("context") == self.context and entry.get("assessment_hash") == expected:
                if authority not in decisions or entry["at"] > decisions[authority]["at"]:
                    decisions[authority] = entry
        # One authority may revise its own review. Another authority cannot lift its rejection.
        review = max(decisions.values(), key=lambda r: (r["decision"] == "rejected", r["at"]), default=None)
        acceptance = "accepted"
        if not classes.issubset(set(policy.accepted_evidence)):
            acceptance = "rejected"
        elif baseline["status"] != "current" or requirement.review_required or policy.require_review:
            acceptance = "review_required"
        if review and acceptance != "rejected" and baseline["status"] == "current":
            acceptance = review.get("decision", "review_required")
            if acceptance == "waived" and not policy.allow_waivers:
                acceptance = "rejected"
        if not applicable:
            verdict, freshness, execution, acceptance = "unknown", "missing", "not_run", "review_required"
            if review and review.get("decision") == "not_applicable":
                acceptance = "accepted"
        closed = applicable and freshness == "current" and execution == "complete" and verdict == "pass" and acceptance == "accepted" and baseline["status"] == "current"
        waiver_allowed = applicable and acceptance == "waived" and policy.allow_waivers and baseline["status"] == "current"
        gate_allowed = closed or waiver_allowed or (not applicable and acceptance == "accepted" and baseline["status"] == "current")
        status = "PASS" if closed else "WAIVED" if acceptance == "waived" else "NOT_APPLICABLE" if not applicable and acceptance == "accepted" else "REVIEW" if not applicable else "ERROR" if execution == "error" else "BLOCKED" if execution == "blocked" else freshness.upper() if freshness != "current" else "FAIL" if verdict == "fail" else "REVIEW" if acceptance == "review_required" else "REJECTED" if acceptance == "rejected" else "UNKNOWN"
        return {"id": identifier, "text": requirement.text, "owner": self.project.modules[identifier.split('.')[0]].owner,
                "method": requirement.method, "applicability": "applicable" if applicable else "not_applicable",
                "freshness": freshness, "execution": execution, "verdict": verdict, "acceptance": acceptance,
                "status": status, "closed": closed, "gate_allowed": gate_allowed, "comparisons": comparisons,
                "evidence": sorted({r for b in support for r in b["evidence"]}), "evidence_classes": sorted(classes),
                "verification_mode": "any_of" if alternative else "all_of", "branches": branches, "selected_branches": selected,
                "assessment_hash": signature, "review": review, "dependencies": producers, "scoped": identifier in self.project.scope}

    def report(self):
        baseline = self.baseline()
        reviews = self._reviews()
        composition = self.project.composition
        baselines = {self.project.manifest.project: baseline}
        linked_reviews = {}
        if composition:
            for unit in composition.units.values():
                supplies_claim = any(key.startswith(unit.name + "::") for key in self.project.scope)
                if unit is composition.root or not (unit.owned or supplies_claim):
                    continue
                local = Project(unit.path, self.project.workspace)
                baselines[unit.name] = self.baseline(local)
                for review in self._reviews(local):
                    key = review.get("requirement", "")
                    if key in local.requirements and (key in local.scope or local.source_root(key) == local.root):
                        identifier = key if local.composition else unit.qualify(key)
                        linked_reviews.setdefault(identifier, []).append(
                            (unit.name, local.policy_for(key), {**review, "requirement": identifier}))
        assessments = []
        for key in self.project.requirements:
            owner = self.project.unit_for(key).name if composition else self.project.manifest.project
            assessments.append(self.assess(key, baselines.get(owner, baseline), reviews, linked_reviews.get(key, ())))
        scoped = [a for a in assessments if a["scoped"]]
        gate = bool(scoped) and bool(self.project.manifest.scenarios) and bool(self.project.manifest.configurations) and baseline["status"] == "current" and all(a["gate_allowed"] for a in scoped)
        analyses = [{"id": identifier, "state": self.states.get(identifier, "missing"), "execution_key": self.keys.get(identifier),
                     "record": self.records.get(identifier), "error": self.failures.get(identifier), "will_run": self.states.get(identifier) != "current"}
                    for identifier in self.project.order]
        report = {"schema": "closure-report/0.1", "id": uuid.uuid4().hex, "created_at": utcnow(),
                "project": self.project.manifest.project, "name": self.project.manifest.name or self.project.manifest.project,
                "source_hash": self.project.source_hash, "context": self.context, "policy": self.project.manifest.policy.model_dump(),
                "model": self.project.model_snapshot(),
                "baseline": baseline, "gate": gate, "scope": self.project.scope, "requirements": assessments, "analyses": analyses,
                "values": self.values, "executed": self.executed, "counts": {s: sum(a["status"] == s for a in scoped) for s in sorted({a["status"] for a in scoped})},
                "assumptions": [{"id": k, **v.model_dump()} for k, v in self.parameters.items() if v.origin == "assumption"],
                "limitations": ["Assessment applies only to declared dependencies, selected context, model validity, and acceptance policy.",
                                "Modelled performance requires corresponding validation or test evidence before being treated as observed performance.",
                                "Local analyses execute trusted code; host and undeclared external dependencies are not isolated."]}
        if composition:
            if baseline["status"] == "changed":
                approved = read_json(within(self.project.root, self.project.manifest.baseline))
                report["baseline_changes"] = contract_changes(approved.get("contract", {}), self.project.obligation_contract())
            gates = composition.gates(assessments, baselines, self.project.requirements)
            report.update(schema="closure-report/0.2", projects=composition.describe(), gates=gates,
                          gate=gates[composition.root.name]["gate"])
        validate_report(report)
        return report

    def explain(self, identifier):
        if identifier not in self.project.requirements:
            raise ClosureError(f"Unknown requirement {identifier}", "UNKNOWN_REF")
        if not self.states:
            self.plan()
        assessment = next(row for row in self.report()["requirements"] if row["id"] == identifier)
        paths = []
        def trace(node, suffix, visited):
            if node in visited:
                return
            parents = [e["source"] for e in self.project.edges if e["target"] == node and e["kind"] in ("consumes", "produces", "verifies")]
            if not parents:
                paths.append([node, *suffix])
            for parent in parents:
                trace(parent, [node, *suffix], visited | {node})
        trace(identifier, [], set())
        return {"requirement": assessment, "paths": paths, "context": self.context, "baseline": self.baseline()}


def approve_baseline(project, reviewer, reason):
    project = project if isinstance(project, Project) else Project(project)
    if not reviewer.strip() or not reason.strip():
        raise ClosureError("Baseline review requires reviewer and rationale", "REVIEW_INVALID")
    if not project.scope or not project.manifest.scenarios or not project.manifest.configurations:
        raise ClosureError("Cannot approve an empty closure scope", "EMPTY_SCOPE")
    contract = project.obligation_contract(approving=True)
    record = {"schema": "closure-baseline/0.1", "contract": contract, "contract_hash": digest(contract), "reviewer": reviewer, "reason": reason, "at": utcnow()}
    atomic_json(within(project.root, project.manifest.baseline), record)
    return record


def record_review(engine, identifier, decision, reviewer, reason):
    if decision not in ("accepted", "waived", "rejected", "not_applicable") or not reviewer.strip() or not reason.strip():
        raise ClosureError("Review needs valid decision, reviewer, and rationale", "REVIEW_INVALID")
    report = engine.plan()
    assessment = next((a for a in report["requirements"] if a["id"] == identifier), None)
    if not assessment:
        raise ClosureError("Unknown requirement", "UNKNOWN_REF")
    if decision == "accepted" and (assessment["verdict"] != "pass" or assessment["freshness"] != "current"):
        raise ClosureError("Acceptance requires current passing evidence", "REVIEW_INVALID")
    if decision == "accepted" and not set(assessment["evidence_classes"]).issubset(engine.project.policy_for(identifier).accepted_evidence):
        raise ClosureError("A review cannot override the policy's accepted evidence classes", "REVIEW_INVALID")
    if decision == "not_applicable" and assessment["applicability"] != "not_applicable":
        raise ClosureError("Applicable requirement cannot be reviewed as not applicable", "REVIEW_INVALID")
    record = {"schema": "closure-review/0.1", "requirement": identifier, "context": engine.context, "decision": decision,
              "assessment_hash": assessment["assessment_hash"], "reviewer": reviewer, "reason": reason, "at": utcnow()}
    atomic_json(engine.project.root / "reviews" / "acceptance" / f"{uuid.uuid4().hex}.json", record)
    return record


def sweep(project, study_path, trusted=False, progress=None):
    project = project if isinstance(project, Project) else Project(project)
    study = Study.model_validate(load_source(within(project.root, study_path)))
    points = study.points or [dict(zip(study.grid, point)) for point in itertools.product(*study.grid.values())]
    total = len(points) * len(study.scenarios) * len(study.configurations)
    if not total or total > 10000:
        raise ClosureError("Sweep must contain 1 to 10000 context points", "STUDY_LIMIT")
    reports = []
    for index, point in enumerate(points):
        point_id = f"{study.study}-{index:04d}-{digest({k:v.model_dump() for k,v in point.items()})[:10]}"
        for scenario in study.scenarios:
            for configuration in study.configurations:
                engine = Engine(project, scenario, configuration, point, point_id)
                reports.append(engine.build(trusted=trusted, progress=progress))
    result = {"schema": "closure-study/0.1", "study": study.study, "expected": total, "completed": len(reports),
              "passed": sum(r["gate"] for r in reports), "failed": sum(not r["gate"] for r in reports), "reports": reports,
              "complete_evidence": all(all(a["state"] == "current" for a in r["analyses"]) for r in reports)}
    StudyResult.model_validate(result)
    atomic_json(project.root / ".closure" / "studies" / f"{study.study}.json", result)
    return result
