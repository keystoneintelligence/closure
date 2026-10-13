import json
import subprocess
import sys
from pathlib import Path
import pytest
from closure.editing import project_lock
from closure.engine import Engine, approve_baseline, record_review
from closure.io import ClosureError, file_digest
from closure.project import Project
from conftest import edit_yaml, runner
from test_rfc_acceptance import artifact_analysis, assessment, input_power


def test_trust_is_required_for_execution(project_dir):
    with pytest.raises(ClosureError) as error:
        Engine(project_dir).build()
    assert error.value.code == "TRUST_REQUIRED"
    assert not (project_dir / ".closure/runs").exists()


def test_library_writers_cannot_overlap(project_dir):
    with project_lock(project_dir):
        with pytest.raises(ClosureError) as error:
            Engine(project_dir).build(trusted=True)
        assert error.value.code == "WRITE_CONFLICT"


def test_engine_prepared_against_old_source_cannot_execute(project_dir):
    engine = Engine(project_dir)
    input_power(project_dir, 120)
    with pytest.raises(ClosureError) as error:
        engine.build(trusted=True)
    assert error.value.code == "SOURCE_CONFLICT"


def test_corrupt_artifact_is_quarantined_and_rebuilt(project_dir):
    artifact_analysis(project_dir)
    before = Engine(project_dir).build(trusted=True)
    artifact = Path(before["values"]["power.budget.shape"]["path"])
    artifact.write_bytes(b"corrupt")
    result = Engine(project_dir).build(trusted=True)
    assert result["gate"]
    assert Engine(project_dir).plan()["gate"]
    assert file_digest(artifact) == result["values"]["power.budget.shape"]["sha256"]
    assert next((project_dir / ".closure/quarantine").iterdir()).read_bytes() == b"corrupt"


def test_scope_empty_cannot_hide_failing_requirement(project_dir):
    Engine(project_dir).build(trusted=True)
    edit_yaml(project_dir / "project.yaml", lambda d: d.update(scope=[]))
    result = Engine(project_dir).plan()
    assert not result["gate"]
    assert not Project(project_dir).check()["valid"]


def test_parameterized_limit_change_requires_baseline_review(project_dir):
    def parameterize(document):
        document["parameters"]["approved_limit"] = {"value": 200, "unit": "W"}
        document["requirements"]["PWR-001"]["verify"]["limit"] = {"ref": "power.approved_limit"}
    edit_yaml(project_dir / "model/power.yaml", parameterize)
    approve_baseline(project_dir, "reviewer", "Review parameterized criterion")
    input_power(project_dir, 120)
    assert not Engine(project_dir).build(trusted=True)["gate"]
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["parameters"]["approved_limit"].update(value=1000))
    result = Engine(project_dir).plan()
    assert assessment(result)["verdict"] == "pass"
    assert not result["gate"] and result["baseline"]["status"] == "changed"
    with pytest.raises(ClosureError) as error:
        Engine(project_dir, overrides={"power.approved_limit": {"value": 2000, "unit": "W"}})
    assert error.value.code == "OBLIGATION_CHANGE"


def test_manual_review_cannot_override_evidence_class_policy(project_dir):
    edit_yaml(project_dir / "project.yaml", lambda d: d["policy"].update(accepted_evidence=["measured"]))
    approve_baseline(project_dir, "test reviewer", "Manufacturing policy requires tests")
    result = Engine(project_dir).build(trusted=True)
    assert not result["gate"] and assessment(result)["acceptance"] == "rejected"
    with pytest.raises(ClosureError, match="evidence classes"):
        record_review(Engine(project_dir), "power.PWR-001", "accepted", "reviewer", "Would bypass evidence policy")


def test_malformed_duplicate_json_outputs_fail(project_dir):
    runner(project_dir, "print('{\"protocol\":\"closure-run/0.1\",\"invocation_id\":' + json.dumps(r['invocation_id']) + ',\"outputs\":{\"total\":{\"value\":999,\"value\":180,\"unit\":\"W\"}}}')")
    result = Engine(project_dir).build(trusted=True)
    assert not result["gate"]
    assert "Duplicate JSON key" in result["analyses"][0]["error"]["message"]


def test_analysis_cannot_modify_frozen_source(project_dir):
    script = project_dir / "analysis/power_budget.py"
    script.write_text(script.read_text() + "\nfrom pathlib import Path\nPath(__file__).write_text('modified')\n")
    result = Engine(project_dir).build(trusted=True)
    assert not result["gate"]
    assert result["analyses"][0]["error"]["code"] == "SOURCE_MUTATION"
    assert "modified" in script.read_text() and "json.dump" in script.read_text()


def test_artifact_inputs_are_hashed_and_available_to_plain_scripts(project_dir):
    asset = project_dir / "design.blend"
    asset.write_bytes(b"opaque external binary fixture")
    edit_yaml(project_dir / "model/payload.yaml", lambda d: (d["parameters"].update(asset={"type":"artifact", "path":"design.blend"}), d["exports"].append("asset")))
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["analyses"]["budget"]["inputs"].update(asset={"ref":"payload.asset"}))
    script = project_dir / "analysis/power_budget.py"
    script.write_text(script.read_text().replace('total = ', "from pathlib import Path\nassert Path(request['inputs']['asset']['path']).is_file()\ntotal = "))
    result = Engine(project_dir).build(trusted=True)
    assert result["gate"]
    asset.write_bytes(b"updated external binary fixture")
    assert assessment(Engine(project_dir).plan())["freshness"] == "stale"


def test_cli_exit_status_and_json_support_ci(project_dir):
    process = subprocess.run([sys.executable, "-m", "closure", "build", "-p", str(project_dir), "--trusted", "--json"], capture_output=True, text=True)
    assert process.returncode == 0 and json.loads(process.stdout)["gate"]
    input_power(project_dir, 120)
    process = subprocess.run([sys.executable, "-m", "closure", "build", "-p", str(project_dir), "--trusted", "--json"], capture_output=True, text=True)
    assert process.returncode == 1 and not json.loads(process.stdout)["gate"]


def test_protected_source_documents_unchanged():
    root = Path(__file__).parents[1]
    expected = {
        "Closure_RFC_0001.md":"721904a15ab605dbaeb5ba0c00be5cb4972baf9338e50935d9cce8f2ede29a5e",
        "MTP.md":"d8c4969c5f1f1e486e0787514821a705a305152af920c535ea3409ce82710b07",
        "NORTH_STAR.md":"dfddd44194f7861e268660f608b14ed4f078791640033443115242fea182c4c4",
    }
    if not any((root/name).exists() for name in expected):
        pytest.skip('Private source documents are excluded from the public distribution')
    assert {name:file_digest(root/name) for name in expected} == expected
