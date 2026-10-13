"""Runtime contracts used for validation and generated JSON Schemas.

Validation checks structure without rewriting signed/hashed historical bytes.
Port-specific units, qualifiers, enum choices and invocation identity are checked
against the authored analysis contract by the engine.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, TypeAdapter

from .models import Datum, Manifest, Module, Policy

Number = StrictInt | Annotated[float, Field(strict=True, allow_inf_nan=False)]
Scalar = Number | StrictBool | StrictStr
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Identity = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
Text = Annotated[str, Field(min_length=1)]
EvidenceClass = Literal["assumed", "predicted", "measured", "established"]
Freshness = Literal["current", "stale", "missing"]
Execution = Literal["complete", "error", "blocked", "not_run"]
Verdict = Literal["pass", "fail", "unknown"]
Acceptance = Literal["accepted", "rejected", "review_required", "waived", "not_applicable"]


class RuntimeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, populate_by_name=True)


class QuantityEnvelope(RuntimeContract):
    type: Literal["quantity"] | None = None
    value: Number
    unit: Text
    qualifiers: dict[str, str] = Field(default_factory=dict)


class ScalarEnvelope(RuntimeContract):
    type: Literal["scalar"] | None = None
    value: Number
    unit: None = None
    qualifiers: dict[str, str] = Field(default_factory=dict)


class BooleanEnvelope(RuntimeContract):
    type: Literal["boolean"] | None = None
    value: bool
    unit: None = None
    qualifiers: dict[str, str] = Field(default_factory=dict)


class TextEnvelope(RuntimeContract):
    type: Literal["string", "enum"] | None = None
    value: str
    unit: None = None
    qualifiers: dict[str, str] = Field(default_factory=dict)


class ArtifactEnvelope(RuntimeContract):
    type: Literal["artifact"] | None = None
    path: Text
    sha256: Hash | None = None
    media_type: Text | None = None
    name: str | None = None
    qualifiers: dict[str, str] = Field(default_factory=dict)


Envelope = QuantityEnvelope | ScalarEnvelope | BooleanEnvelope | TextEnvelope | ArtifactEnvelope
envelope_adapter = TypeAdapter(Envelope)


class QuantityValue(QuantityEnvelope):
    type: Literal["quantity"]


class ScalarValue(ScalarEnvelope):
    type: Literal["scalar"]


class BooleanValue(BooleanEnvelope):
    type: Literal["boolean"]


class TextValue(TextEnvelope):
    type: Literal["string", "enum"]


class ArtifactValue(ArtifactEnvelope):
    type: Literal["artifact"]
    sha256: Hash
    name: str


Value = Annotated[QuantityValue | ScalarValue | BooleanValue | TextValue | ArtifactValue, Field(discriminator="type")]


class Context(RuntimeContract):
    scenario: Text
    configuration: Text
    point: Text


class Executable(RuntimeContract):
    path: Text
    sha256: Hash


class Tools(RuntimeContract):
    executables: dict[str, Executable] = Field(default_factory=dict)
    files: dict[str, Hash] = Field(default_factory=dict)


class RunnerRequest(RuntimeContract):
    protocol: Literal["closure-run/0.1"]
    invocation_id: Identity
    context: Context
    inputs: dict[str, Value]
    settings: dict[str, Scalar]
    tools: Tools
    seed: int | None
    output_dir: Text


class RunnerResponse(RuntimeContract):
    protocol: Literal["closure-run/0.1"]
    invocation_id: Identity
    outputs: dict[str, Envelope]
    converged: bool | None = None
    residuals: dict[str, Number] = Field(default_factory=dict)


class Environment(RuntimeContract):
    python: str
    interpreter: str
    platform: str
    engine_sources: dict[str, Hash] = Field(default_factory=dict)
    process_environment: dict[str, str | None] = Field(default_factory=dict)
    packages: list[Annotated[list[str], Field(min_length=2, max_length=2)]]


class EvidenceRecord(RuntimeContract):
    protocol: Literal["closure-evidence/0.1"]
    id: Identity
    analysis: Text
    execution_key: Hash
    started_at: Text
    finished_at: Text
    context: Context
    inputs: dict[str, Value]
    outputs: dict[str, Value]
    inputs_archived: bool = False  # Older records retained only input digests.
    sources: dict[str, Hash]
    environment: Environment
    command: list[str] = Field(min_length=1)
    upstream: dict[str, Hash]
    tools: Tools = Field(default_factory=Tools)
    evidence_class: EvidenceClass
    logs: str
    converged: bool | None
    residuals: dict[str, Number]
    execution: Literal["complete"]
    settings: dict[str, Scalar]
    seed: int | None
    limitations: list[str]
    record_hash: Hash


class Comparison(RuntimeContract):
    verdict: Verdict
    actual: Scalar | None
    limit: Scalar | None
    margin: Number | None
    ref: str
    unit: str | None = None
    op: Literal["lte", "gte", "lt", "gt", "eq", "ne"] | None = None
    description: str = ""
    branch: int | None = None


class VerificationBranch(RuntimeContract):
    index: int = Field(ge=0)
    ref: str
    freshness: Freshness
    execution: Execution
    verdict: Verdict
    comparison: Comparison | None
    dependencies: list[str]
    evidence: list[Identity]
    evidence_classes: list[EvidenceClass]
    evidence_allowed: bool


class ReviewRecord(RuntimeContract):
    schema_version: Literal["closure-review/0.1"] = Field(alias="schema")
    requirement: str
    context: Context
    decision: Literal["accepted", "waived", "rejected", "not_applicable"]
    assessment_hash: Hash
    reviewer: Text
    reason: Text
    at: Text


class Assessment(RuntimeContract):
    id: str
    text: str
    owner: str
    method: Literal["analysis", "test", "inspection", "demonstration"]
    applicability: Literal["applicable", "not_applicable"]
    freshness: Freshness
    execution: Execution
    verdict: Verdict
    acceptance: Acceptance
    status: Literal["PASS", "WAIVED", "NOT_APPLICABLE", "REVIEW", "ERROR", "BLOCKED", "STALE", "MISSING", "FAIL", "REJECTED", "UNKNOWN"]
    closed: bool
    gate_allowed: bool
    comparisons: list[Comparison]
    evidence: list[Identity]
    evidence_classes: list[EvidenceClass]
    assessment_hash: Hash
    review: ReviewRecord | None
    dependencies: list[str]
    scoped: bool
    # Optional for immutable snapshots from earlier engine revisions.
    verification_mode: Literal["all_of", "any_of"] | None = None
    branches: list[VerificationBranch] = Field(default_factory=list)
    selected_branches: list[int] = Field(default_factory=list)


class Edge(RuntimeContract):
    source: str
    target: str
    kind: Literal["contains", "consumes", "produces", "verifies", "derived_from"]


class ModelSnapshot(RuntimeContract):
    project: Manifest
    modules: list[Module]
    edges: list[Edge]
    protected_parameters: list[str]


class BaselineAssessment(RuntimeContract):
    status: Literal["current", "changed", "missing"]
    current_hash: Hash
    approved_hash: str | None = None
    reviewer: str | None = None
    message: str


class Diagnostic(RuntimeContract):
    code: str
    message: str
    location: str = ""


class AnalysisState(RuntimeContract):
    id: str
    state: Literal["current", "stale", "missing", "error", "blocked"]
    execution_key: Hash | None
    record: EvidenceRecord | None
    error: Diagnostic | None
    will_run: bool


class Assumption(Datum):
    id: str


class Report(RuntimeContract):
    schema_version: Literal["closure-report/0.1"] = Field(alias="schema")
    id: Identity
    created_at: Text
    project: str
    name: str
    source_hash: Hash
    context: Context
    policy: Policy
    model: ModelSnapshot
    baseline: BaselineAssessment
    gate: bool
    scope: list[str]
    requirements: list[Assessment]
    analyses: list[AnalysisState]
    values: dict[str, Value]
    executed: list[str]
    counts: dict[str, int]
    assumptions: list[Assumption]
    limitations: list[str]
    report_hash: Hash | None = None


class StudyResult(RuntimeContract):
    schema_version: Literal["closure-study/0.1"] = Field(alias="schema")
    study: str
    expected: int = Field(ge=1)
    completed: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    reports: list[Report]
    complete_evidence: bool


RUNTIME_SCHEMAS = {"runner-request": RunnerRequest, "runner-response": RunnerResponse,
                   "evidence": EvidenceRecord, "report": Report, "study-result": StudyResult,
                   "review": ReviewRecord}
