"""Versioned, language-neutral source contracts. Unknown fields are errors."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, allow_inf_nan=False)


class Port(Contract):
    type: Literal["quantity", "scalar", "boolean", "string", "enum", "artifact"] = "quantity"
    unit: str | None = None
    qualifiers: dict[str, str] = Field(default_factory=dict)
    choices: list[str] = Field(default_factory=list)
    description: str = ""

    @model_validator(mode="after")
    def complete(self):
        if self.type == "quantity" and not self.unit:
            raise ValueError("quantity requires a unit")
        if self.type != "quantity" and self.unit:
            raise ValueError("only a quantity may declare a unit")
        if self.type == "enum" and not self.choices:
            raise ValueError("enum requires choices")
        return self


class Datum(Contract):
    value: float | int | bool | str | None = None
    unit: str | None = None
    type: Literal["quantity", "scalar", "boolean", "string", "enum", "artifact"] | None = None
    path: str | None = None
    qualifiers: dict[str, str] = Field(default_factory=dict)
    choices: list[str] = Field(default_factory=list)
    origin: Literal["assumption", "design", "predicted", "measured", "established"] = "design"
    rationale: str = ""
    description: str = ""

    @model_validator(mode="after")
    def infer(self):
        if self.type is None:
            self.type = "artifact" if self.path else "quantity" if self.unit else "boolean" if isinstance(self.value, bool) else "string" if isinstance(self.value, str) else "scalar"
        if self.type == "artifact":
            if not self.path or self.value is not None:
                raise ValueError("artifact requires path and cannot have a scalar value")
        elif self.value is None:
            raise ValueError("datum requires a value")
        if self.type in ("quantity", "scalar") and (isinstance(self.value, bool) or not isinstance(self.value, (int, float))):
            raise ValueError("numeric datum requires a finite number")
        if self.type == "boolean" and not isinstance(self.value, bool):
            raise ValueError("boolean requires true or false")
        if self.type in ("string", "enum") and not isinstance(self.value, str):
            raise ValueError("text datum requires a string")
        if self.type == "enum" and self.value not in self.choices:
            raise ValueError("value is not an enum choice")
        self.port()
        return self

    def port(self):
        return Port(type=self.type, unit=self.unit, qualifiers=self.qualifiers, choices=self.choices, description=self.description)


class Binding(Contract):
    ref: str
    unit: str | None = None
    qualifiers: dict[str, str] = Field(default_factory=dict)


class Criterion(Contract):
    actual: Binding
    op: Literal["lte", "gte", "lt", "gt", "eq", "ne"]
    limit: Datum | Binding
    description: str = ""


class Verification(Contract):
    all_of: list[Criterion] | None = None
    any_of: list[Criterion] | None = None

    @model_validator(mode="after")
    def one_group(self):
        if (self.all_of is None) == (self.any_of is None) or not (self.all_of or self.any_of):
            raise ValueError("verification requires exactly one nonempty all_of or any_of")
        return self


class Run(Contract):
    argv: list[str] = Field(min_length=1)
    sources: list[str] = Field(min_length=1)
    environment_lock: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    tools: dict[str, str] = Field(default_factory=dict)
    tool_files: list[str] = Field(default_factory=list)
    timeout: float = Field(default=120, gt=0, le=3600)
    max_output_bytes: int = Field(default=2_000_000, gt=0, le=20_000_000)
    uncontrolled_dependencies: list[str] = Field(default_factory=list)
    stochastic: bool = False
    seed: int | None = None


class Analysis(Contract):
    description: str = ""
    run: Run
    inputs: dict[str, Binding] = Field(default_factory=dict)
    outputs: dict[str, Port] = Field(min_length=1)
    valid_when: list[Criterion] = Field(default_factory=list)
    evidence_class: Literal["assumed", "predicted", "measured", "established"] = "predicted"
    solver: bool = False
    settings: dict[str, float | int | bool | str] = Field(default_factory=dict)


class Requirement(Contract):
    text: str = Field(min_length=1)
    applies_to: list[str] = Field(default_factory=lambda: ["nominal"])
    configurations: list[str] = Field(default_factory=lambda: ["default"])
    verify: Criterion | Verification | None = None
    derived_from: list[str] = Field(default_factory=list)
    review_required: bool = False
    required: bool = True
    method: Literal["analysis", "test", "inspection", "demonstration"] = "analysis"


class Module(Contract):
    schema_version: Literal["closure/0.1"] = Field(alias="schema")
    module: str
    name: str = ""
    owner: str
    description: str = ""
    color: str | None = None
    parameters: dict[str, Datum] = Field(default_factory=dict)
    exports: list[str] = Field(default_factory=list)
    analyses: dict[str, Analysis] = Field(default_factory=dict)
    requirements: dict[str, Requirement] = Field(default_factory=dict)


class ContextSpec(Contract):
    description: str = ""
    overrides: dict[str, Datum] = Field(default_factory=dict)


class Policy(Contract):
    name: str = "concept"
    accepted_evidence: list[Literal["assumed", "predicted", "measured", "established"]] = Field(default_factory=lambda: ["assumed", "predicted"])
    require_review: bool = False
    allow_waivers: bool = False
    description: str = "Analytical concept assessment within declared model validity."


class Manifest(Contract):
    schema_version: Literal["closure/0.1"] = Field(alias="schema")
    project: str
    name: str = ""
    description: str = ""
    modules: list[str] = Field(default_factory=lambda: ["model/*.yaml"])
    scenarios: dict[str, ContextSpec] = Field(default_factory=lambda: {"nominal": ContextSpec()})
    configurations: dict[str, ContextSpec] = Field(default_factory=lambda: {"default": ContextSpec()})
    policy: Policy = Field(default_factory=Policy)
    scope: list[str] = Field(default_factory=lambda: ["*"])
    baseline: str = "reviews/baseline.json"
    reviews: list[str] = Field(default_factory=lambda: ["reviews/acceptance/*.json"])


class Study(Contract):
    schema_version: Literal["closure/0.1"] = Field(alias="schema")
    study: str
    scenarios: list[str] = Field(default_factory=lambda: ["nominal"])
    configurations: list[str] = Field(default_factory=lambda: ["default"])
    grid: dict[str, list[Datum]] = Field(default_factory=dict)
    points: list[dict[str, Datum]] = Field(default_factory=list)

    @model_validator(mode="after")
    def grid_or_points(self):
        if bool(self.grid) == bool(self.points):
            raise ValueError("study requires a grid or explicit points, exclusively")
        if any(not values for values in self.grid.values()):
            raise ValueError("study axes cannot be empty")
        return self
