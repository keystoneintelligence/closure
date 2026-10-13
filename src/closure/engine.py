"""Plan, execute, assess, and explain a selected engineering context."""
from __future__ import annotations

import fnmatch
import itertools
import operator
import time
import uuid
from pathlib import Path
from . import __version__
from .evidence import EvidenceStore, environment_identity, resolve_executable, source_snapshot, tool_identity, utcnow
from .io import ClosureError, atomic_json, digest, file_digest, load_source, read_json, within
from .models import Binding, Criterion, Datum, Study
from .protocol import Report, StudyResult
from .project import Project, criteria, refs
from .units import convert
from .editing import project_lock

OPS = {"lte": operator.le, "gte": operator.ge, "lt": operator.lt, "gt": operator.gt, "eq": operator.eq, "ne": operator.ne}


class Engine:
    def __init__(self, project: Project | str | Path, scenario=None, configuration=None, overrides=None, point="baseline"):
        self.project = project if isinstance(project, Project) else Project(project)
        self.store = EvidenceStore(self.project.root)
        manifest = self.project.manifest
        scenario = scenario if scenario is not None else next(iter(manifest.scenarios), None)
        configuration = configuration if configuration is not None else next(iter(manifest.configurations), None)
        self.context = {"scenario": scenario, "configuration": configuration, "point": point}
        if scenario not in manifest.scenarios or configuration not in manifest.configurations:
            raise ClosureError("Selected scenario/configuration is not declared", "UNKNOWN_CONTEXT")
        if set(overrides or {}) & self.project.protected_parameters():
            raise ClosureError("Study or ad hoc overrides cannot alter inputs that define requirement limits; propose and review an obligation change", "OBLIGATION_CHANGE")
        combined = {**manifest.configurations[configuration].overrides, **manifest.scenarios[scenario].overrides, **(overrides or {})}
        self.parameters = self.project.resolve_parameters(combined)
        self.environment = environment_identity()
        self.states, self.records, self.keys, self.sources, self.values = {}, {}, {}, {}, {}
        self.tools = {}
        self.failures = {}
        self.executed = []
        for identifier, datum in self.parameters.items():
            if datum.type == "artifact":
                artifact = within(self.project.root, datum.path)
                if artifact.is_file():
                    self.values[identifier] = {"type": "artifact", "path": str(artifact), "sha256": file_digest(artifact), "name": artifact.name,
                                               "qualifiers": datum.qualifiers}
            else:
                self.values[identifier] = {"value": datum.value, "unit": datum.unit, "type": datum.type, "qualifiers": datum.qualifiers}

    def _slot(self, identifier):
        return digest({"analysis": identifier, "context": self.context})

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
        self.sources[identifier] = source_snapshot(self.project, analysis)
        identities = {}
        bindings = list(analysis.inputs.values()) + [ref for c in analysis.valid_when for ref in refs(c)]
        for binding in bindings:
            if binding.ref in self.parameters:
                parameter = self.parameters[binding.ref]
                identities[binding.ref] = {"source": parameter.model_dump(), "resolved": self.values.get(binding.ref)}
            else:
                producer = self.project.producers[binding.ref]
                identities[binding.ref] = {"producer": self.keys.get(producer), "run": self.records.get(producer, {}).get("record_hash")}
        executable = resolve_executable(analysis.run.argv)[0]
        self.tools[identifier] = tool_identity(analysis.run, self.project.root)
        identity = {"protocol": "closure-run/0.1", "engine": __version__, "analysis": identifier,
                    "contract": analysis.model_dump(), "sources": self.sources[identifier], "environment": self.environment,
                    "executable": {"path": executable, "sha256": file_digest(executable)}, "tools": self.tools[identifier], "inputs": identities, "context": self.context}
        self.keys[identifier] = digest(identity)
        state, record = self.store.lookup(self.keys[identifier], self._slot(identifier))
        if analysis.run.uncontrolled_dependencies or (analysis.run.stochastic and analysis.run.seed is None):
            state, record = "stale" if state == "current" else state, None
        blocked = any(self.states.get(dependency) != "current" for dependency in self.project.dependencies[identifier])
        if blocked:
            state, record = "stale" if state == "current" else state, None
        self.states[identifier] = state
        if record:
            if record["context"] != self.context or record["analysis"] != identifier:
                self.states[identifier] = "missing"
            else:
                self._use_record(identifier, record)

    def _use_record(self, identifier, record):
        self.records[identifier] = record
        self.states[identifier] = "current"
        for name, value in record["outputs"].items():
            self.values[f"{identifier}.{name}"] = value

    def plan(self):
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
        with project_lock(self.project.root):
            if Project(self.project.manifest_path).source_hash != self.project.source_hash:
                raise ClosureError("Project source changed after this engine was prepared", "SOURCE_CONFLICT")
            return self._build(force=force, progress=progress)

    def _build(self, force=False, progress=None):
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
                if force:
                    # A failed forced rerun cannot leave an old passing record
                    # available to dependent analyses or requirement assessment.
                    self.store.invalidate(self.keys[identifier])
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
                record = self.store.execute(self.project, identifier, analysis, self.keys[identifier], self._slot(identifier),
                                            self.context, inputs, self.sources[identifier], self.environment,
                                            {dep: self.records[dep]["record_hash"] for dep in sorted(self.project.dependencies[identifier])}, self.tools[identifier])
                self._use_record(identifier, record)
                self.executed.append(identifier)
                notify("completed", seconds=time.monotonic() - started)
            except ClosureError as exc:
                self.failures[identifier] = exc.as_dict()
                self.states[identifier] = "blocked" if exc.code in ("BLOCKED", "INVALID_DOMAIN", "MISSING_INPUT") else "error"
                notify(self.states[identifier], error=exc.as_dict())
        report = self.report()
        return self.store.save_report(report)

    def baseline(self):
        path = within(self.project.root, self.project.manifest.baseline)
        current = digest(self.project.obligation_contract())
        if not path.exists():
            return {"status": "missing", "current_hash": current, "message": "Initial obligations need a recorded baseline review."}
        approved = read_json(path)
        valid = approved.get("contract_hash") == current and bool(approved.get("reviewer")) and digest(approved.get("contract")) == current
        return {"status": "current" if valid else "changed", "current_hash": current,
                "approved_hash": approved.get("contract_hash"), "reviewer": approved.get("reviewer"),
                "message": "Obligations match the reviewed baseline." if valid else "Requirements, scope, context set, or policy changed; separate review required."}

    def _reviews(self):
        reviews = []
        for pattern in self.project.manifest.reviews:
            within(self.project.root, pattern)
            for path in self.project.root.glob(pattern):
                review = read_json(path)
                if review.get("reviewer") and review.get("reason"):
                    reviews.append(review)
        return sorted(reviews, key=lambda r: r.get("at", ""))

    def _criterion_support(self, criterion, index):
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
                "evidence_allowed": classes.issubset(self.project.manifest.policy.accepted_evidence)}

    def assess(self, identifier, baseline, reviews):
        requirement = self.project.requirements[identifier]
        applicable = self.context["scenario"] in requirement.applies_to and self.context["configuration"] in requirement.configurations
        conditions = criteria(requirement.verify)
        sources = [binding.ref for c in conditions for binding in refs(c)]
        producers = sorted({self.project.producers[ref] for ref in sources if ref in self.project.producers})
        alternative = bool(conditions) and not isinstance(requirement.verify, Criterion) and requirement.verify.any_of is not None
        branches = [self._criterion_support(c, i) for i, c in enumerate(conditions)]
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
        policy = self.project.manifest.policy
        signature = digest({"requirement": requirement.model_dump(), "context": self.context, "policy": policy.model_dump(),
                            "records": {p: self.records.get(p, {}).get("record_hash") for p in producers},
                            "inputs": {r: self.parameters[r].model_dump() for r in sources if r in self.parameters}})
        review = next((r for r in reversed(reviews) if r.get("requirement") == identifier and r.get("assessment_hash") == signature and r.get("context") == self.context), None)
        acceptance = "accepted"
        if not classes.issubset(set(policy.accepted_evidence)):
            acceptance = "rejected"
        elif baseline["status"] != "current" or requirement.review_required or policy.require_review:
            acceptance = "review_required"
        if review and acceptance != "rejected":
            acceptance = review.get("decision", "review_required")
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
        assessments = [self.assess(identifier, baseline, reviews) for identifier in self.project.requirements]
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
        Report.model_validate(report)
        return report

    def explain(self, identifier):
        if identifier not in self.project.requirements:
            raise ClosureError(f"Unknown requirement {identifier}", "UNKNOWN_REF")
        if not self.states:
            self.plan()
        assessment = self.assess(identifier, self.baseline(), self._reviews())
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
    contract = project.obligation_contract()
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
    if decision == "accepted" and not set(assessment["evidence_classes"]).issubset(engine.project.manifest.policy.accepted_evidence):
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
