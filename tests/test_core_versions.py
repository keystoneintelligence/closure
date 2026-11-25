"""Version boundaries for live source, published schemas and archived snapshots."""
import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from closure.engine import Engine
from closure.io import ClosureError, canonical
from closure.project import Project
from closure.protocol import validate_report, validate_saved_report
from closure.schemas import schemas
from conftest import edit_yaml


def test_unmarked_02_manifest_preserves_composed_scope(tmp_path):
    path = tmp_path / "project.json"
    manifest = {"project": "system", "schema": "closure/0.2", "modules": ["power.json"]}
    module = {"module": "power", "owner": "Power team", "schema": "closure/0.2"}
    (tmp_path / "power.json").write_text(json.dumps(module))
    contracts = schemas()
    standalone = Draft202012Validator(contracts["project"])
    composed = Draft202012Validator(contracts["composed-project"])

    path.write_text(json.dumps(manifest))
    assert list(Project(path).modules) == ["system::power"]
    assert composed.is_valid(manifest) and not standalone.is_valid(manifest)

    manifest["kind"] = "standalone"
    path.write_text(json.dumps(manifest))
    assert list(Project(path).modules) == ["power"]
    assert standalone.is_valid(manifest) and not composed.is_valid(manifest)

    manifest["children"] = {}
    path.write_text(json.dumps(manifest))
    with pytest.raises(ClosureError) as error:
        Project(path)
    assert error.value.code == "SCHEMA"
    assert not standalone.is_valid(manifest) and not composed.is_valid(manifest)


@pytest.mark.parametrize("filename", ["project.yaml", "model/power.yaml"])
def test_legacy_live_source_requires_migration(project_dir, filename):
    path = project_dir / filename
    edit_yaml(path, lambda doc: doc.update(schema="closure/0.1"))
    with pytest.raises(ClosureError) as error:
        Project(project_dir)
    assert error.value.code == "SOURCE_VERSION"
    assert error.value.location == str(path)
    assert "closure/0.2" in str(error.value)
    if filename == "project.yaml":
        assert "kind: standalone" in str(error.value)


def test_generated_contracts_use_only_current_versions():
    for name, schema in schemas().items():
        assert schema["$id"] == f"urn:closure:schema:0.2:{name}"
        property_name = "protocol" if name in {"evidence", "runner-request", "runner-response"} else "schema"
        assert schema["properties"][property_name]["const"].endswith("/0.2")
        assert "/0.1" not in json.dumps(schema)


def test_early_composed_report_retains_its_embedded_core_versions(project_dir):
    edit_yaml(project_dir / "project.yaml", lambda doc: doc.pop("kind"))
    report = Engine(project_dir).plan()
    assert report["schema"] == "closure-report/0.2"
    for module in report["model"]["modules"]:
        module["schema"] = "closure/0.1"
    assessment = report["requirements"][0]
    review = {"schema": "closure-review/0.1", "requirement": assessment["id"],
              "context": report["context"], "decision": "accepted", "assessment_hash": assessment["assessment_hash"],
              "reviewer": "Power team", "reason": "Reviewed the assessment", "at": report["created_at"]}
    assessment["review"] = review
    original = canonical(report)
    validate_saved_report(report)
    assert canonical(report) == original
    with pytest.raises(ValidationError):
        validate_report(report)

    review["schema"] = "closure-review/0.2"
    with pytest.raises(ValidationError):
        validate_saved_report(report)
