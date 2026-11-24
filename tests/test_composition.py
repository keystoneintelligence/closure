"""End-to-end checks for the generic, four-project power example."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from closure.cli import main
from closure.engine import Engine, approve_baseline
from closure.io import ClosureError
from closure.project import Project
from conftest import edit_yaml

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "composed-power"


@pytest.fixture
def assembly(tmp_path):
    root = tmp_path / "assembly"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns(".closure", "__pycache__"))
    return root


def test_shared_execution_and_local_acceptance(assembly):
    first = Engine(assembly).verify(trusted=True)
    assert first["gate"] and len(first["executed"]) == 4
    assert sum(key.startswith("reference::") for key in first["executed"]) == 1
    assert not first["projects"]["reference"]["owned"]
    limit = assembly / "model/budget.yaml"
    limit.write_text(limit.read_text().replace("110", "100"))
    changed = Engine(assembly).verify(trusted=True)
    assert changed["executed"] == [] and not changed["gate"]
    assert changed["gates"]["electronics"]["gate"] and changed["gates"]["cooling"]["gate"]
    comparison = changed["comparison"]
    assert comparison["previous"] == first["id"]
    assert any("110 W to 100 W" in line and "104 W" in line for line in comparison["changes"])
    assert all("Reused" in decision["reason"] for decision in comparison["decisions"])
    assert any("maximum" in line for line in changed["baseline_changes"])
    assert changed["requirements"][0]["comparisons"][0]["margin"] == -4
    independent = Engine(assembly / "electronics").verify(trusted=True)
    assert independent["gate"] and independent["executed"] == []
    assert {a["id"] for a in independent["analyses"]} == {"electronics::load.scale", "reference::profile.evaluate"}
    assert "cooling" not in independent["projects"]


def test_containment_and_file_url(assembly):
    path = assembly / "project.yaml"
    path.write_text(path.read_text().replace("path: electronics}", "path: " + (assembly / "electronics").as_uri() + "}"))
    assert len(Project(assembly).order) == 4
    path.write_text(path.read_text().replace("path: cooling}", "path: .}"))
    with pytest.raises(ClosureError, match="Containment cycle"):
        Project(assembly)


def test_required_child_and_supplier_contract(assembly):
    local = assembly / "cooling/model/load.yaml"
    local.write_text(local.read_text().replace("value: 60", "value: 50"))
    report = Engine(assembly).verify(trusted=True)
    assert not report["gates"]["cooling"]["gate"] and not report["gate"]
    path = assembly / "cooling/project.yaml"
    path.write_text(path.read_text().replace("export: load", "export: secret"))
    with pytest.raises(ClosureError, match="does not export secret"):
        Project(assembly)


def test_upward_definition_and_lateral_result(assembly):
    # The component supplies the thermal model's input before its own gate closes.
    component = assembly / "electronics"
    thermal = assembly / "reference"
    manifest = component / "project.yaml"
    manifest.write_text(manifest.read_text().replace("load.scale.demand}", "load.scale.demand, geometry: load.geometry}"))
    model = component / "model/load.yaml"
    model.write_text(model.read_text().replace("analyses:", "parameters: {geometry: {value: 26, unit: W}}\nanalyses:"))
    path = thermal / "project.yaml"
    path.write_text(path.read_text() + "imports: {geometry: {path: ../electronics, export: geometry}}\n")
    model = thermal / "model/load.yaml"
    model.write_text(model.read_text().replace("ref: profile.reference", 'ref: "@geometry"'))
    assert Engine(component).verify(trusted=True)["executed"] == ["reference::profile.evaluate", "electronics::load.scale"]
    manifest.write_text(manifest.read_text().replace("geometry: load.geometry", "geometry: load.scale.demand"))
    with pytest.raises(ClosureError, match="Computational cycle"):
        Project(component)


def test_git_identity_and_dependency_reuse(assembly):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=assembly, text=True).strip()

    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Power allocations")
    initial = Engine(assembly).verify(trusted=True)
    assert initial["revision"] == {"state": "committed inputs", "commit": git("rev-parse", "HEAD"), "files": []}
    (assembly / "notes.md").write_text("Documentation")
    unchanged = Engine(assembly).verify(trusted=True)
    assert unchanged["executed"] == []
    code = assembly / "cooling/scale.py"
    code.write_text(code.read_text() + "# Updated implementation\n")
    changed = Engine(assembly).verify(trusted=True)
    assert changed["revision"]["files"] == ["cooling/scale.py"]
    assert changed["executed"] == ["cooling::load.scale", "system::budget.sum"]
    from closure.comparison import compare_git
    diff = compare_git(Project(assembly / "cooling"), "HEAD")
    assert diff["affected_analyses"] == ["cooling::load.scale"]


@pytest.mark.parametrize("group,name,shadowed", [("scenarios", "nominal", False),
                                                ("configurations", "default", False),
                                                ("configurations", "default", True)])
def test_plan_base_tracks_child_power_override(assembly, capsys, group, name, shadowed):
    electronics = assembly / "electronics"
    manifest = electronics / "project.yaml"

    def use_local_reference(model):
        model["parameters"] = {"reference": {"value": 26, "unit": "W"}}
        model["analyses"]["scale"]["inputs"]["reference"]["ref"] = "load.reference"

    def configure_reference(manifest):
        manifest[group] = {name: {"overrides": {"load.reference": {"value": 26, "unit": "W"}}}}
        if shadowed:
            manifest["scenarios"] = {"nominal": {"overrides": {"load.reference": {"value": 26, "unit": "W"}}}}

    edit_yaml(electronics / "model/load.yaml", use_local_reference)
    edit_yaml(manifest, configure_reference)
    for root in (electronics, assembly):
        approve_baseline(root, "System Engineering", "Reviewed the power allocations")
    (assembly / ".gitignore").write_text(".closure/\n")
    for args in (["init", "-q"], ["add", "."], ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                                                "commit", "-qm", "Power reference values"]):
        subprocess.run(["git", *args], cwd=assembly, capture_output=True, check=True)
    assert Engine(assembly).verify(trusted=True)["gate"]

    edit_yaml(manifest, lambda d: d[group][name]["overrides"]["load.reference"].update(value=33))
    assert main(["plan", "--project", str(assembly), "--base", "HEAD", "--json"]) == 0
    delta = json.loads(capsys.readouterr().out)["base_comparison"]
    assert delta["changed_files"] == ["electronics/project.yaml"]
    assert delta["context_changed"] == (not shadowed)
    expected_analyses = [] if shadowed else ["electronics::load.scale", "system::budget.sum"]
    expected_requirements = [] if shadowed else ["electronics::load.local_budget", "system::budget.power"]
    assert delta["affected_analyses"] == expected_analyses
    assert delta["affected_requirements"] == expected_requirements
    report = Engine(assembly).verify(trusted=True)
    assert report["executed"] == expected_analyses
    assert report["gate"] == shadowed


def test_import_contracts_empty_groups_and_context(assembly):
    path = assembly / "project.yaml"
    original = path.read_text()
    path.write_text(original.replace("export: demand}", "export: demand, port: {type: boolean}}"))
    with pytest.raises(ClosureError, match="incompatible type"):
        Project(assembly)
    path.write_text(original.replace("export: demand}", "export: demand, port: {type: quantity, unit: kg}}"))
    with pytest.raises(ClosureError, match="Cannot convert"):
        Project(assembly)
    path.write_text(original + "scenarios: {nominal: {}, hot: {}}\n")
    assert not Project(assembly).check()["valid"]
    with pytest.raises(ClosureError, match="does not declare hot"):
        Engine(assembly, scenario="hot")
    path.write_text(original.replace("  cooling: {path: cooling}", "  cooling: {path: cooling}\n  reference: {path: reference}"))
    report = Engine(assembly).verify(trusted=True)
    assert not report["gate"] and "No applicable obligations" in report["gates"]["reference"]["reasons"]


def test_claim_import_and_parent_evidence_policy(assembly):
    supplier = assembly / "electronics/project.yaml"
    supplier.write_text(supplier.read_text().replace("load.scale.demand}", "load.scale.demand, qualified: load.local_budget}"))
    path = assembly / "project.yaml"
    path.write_text(path.read_text().replace("  electronics: {path: electronics}", "") +
                    "  evidence: {path: electronics, export: qualified}\nrequired_claims: [evidence]\n"
                    "policy: {accepted_evidence: [measured]}\n")
    engine = Engine(assembly)
    report = engine.verify(trusted=True)
    claim = next(row for row in report["requirements"] if row["id"] == "electronics::load.local_budget")
    assert claim["scoped"] and claim["acceptance"] == "rejected" and not report["gate"]

def test_artifact_bytes_from_shared_project(assembly):
    # Replace the synthetic profile with a declared data file consumed by both components.
    path = assembly / "reference/project.yaml"
    path.write_text(path.read_text().replace("profile.evaluate.power", "profile.dataset"))
    path = assembly / "reference/model/load.yaml"
    path.write_text("schema: closure/0.1\nmodule: profile\nowner: Test Engineering\n"
                    "parameters: {dataset: {type: artifact, path: load.txt}}\n")
    dataset = assembly / "reference/load.txt"
    dataset.write_text("26")
    for name in ("electronics", "cooling"):
        model = assembly / name / "model/load.yaml"
        model.write_text(model.read_text().replace('ref: "@reference", unit: W', 'ref: "@reference"'))
        code = assembly / name / "scale.py"
        code.write_text('from pathlib import Path\n' + code.read_text().replace('request["inputs"]["reference"]["value"]',
                        'float(Path(request["inputs"]["reference"]["path"]).read_text())'))
    first = Engine(assembly).verify(trusted=True)
    assert first["values"]["system::budget.sum.total"]["value"] == 104
    dataset.write_text("28")
    second = Engine(assembly).verify(trusted=True)
    assert len(second["executed"]) == 3 and second["values"]["system::budget.sum.total"]["value"] == 112
    from closure.evidence import EvidenceStore
    store = EvidenceStore(assembly)
    original = first["analyses"][0]["record"]["inputs"]["reference"]
    store.artifact_path(original).write_bytes(b"corrupt")
    with pytest.raises(ClosureError, match="do not match"):
        store.load_report(first["id"])
