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
from closure.reporting import explain_saved_report
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


@pytest.mark.parametrize("second,count", [("electronics", 1), ("cooling", 2)], ids=["duplicate-alias", "distinct-child"])
def test_child_aliases_count_distinct_component_obligations(assembly, second, count):
    children = {"first_component": {"path": "electronics"}, "second_component": {"path": second}}
    edit_yaml(assembly / "project.yaml", lambda d: d.update(scope=[], children=children))
    approve_baseline(assembly, "System Engineering", "Reviewed the component allocations")
    report = Engine(assembly).verify(trusted=True)

    assert report["projects"]["system"]["children"] == {"first_component": "electronics", "second_component": second}
    assert set(report["scope"]) == {"electronics::load.local_budget", f"{second}::load.local_budget"}
    assert report["gate"] and report["counts"] == {"PASS": count}
    assert report["gates"]["system"]["applicable"] == count
    assert report["gates"]["electronics"]["applicable"] == report["gates"][second]["applicable"] == 1


def test_shared_profile_obligation_counts_once_in_assembly(assembly):
    profile = assembly / "reference"
    edit_yaml(profile / "model/load.yaml", lambda d: d.update(requirements={
        "power": {"text": "The shared profile supplies the reference power.",
                  "verify": {"actual": {"ref": "profile.evaluate.power"}, "op": "eq",
                             "limit": {"ref": "profile.reference"}}}}))
    for component in ("electronics", "cooling"):
        edit_yaml(assembly / component / "project.yaml", lambda d: d.update(children={"profile": {"path": "../reference"}}))
    for unit in (profile, assembly / "electronics", assembly / "cooling", assembly):
        approve_baseline(unit, "System Engineering", "Reviewed the power allocations")
    report = Engine(assembly).verify(trusted=True)

    assert report["gate"] and report["counts"] == {"PASS": 4}
    for component in ("electronics", "cooling"):
        assert report["projects"][component]["children"] == {"profile": "reference"}
    assert {key: gate["applicable"] for key, gate in report["gates"].items()} == {
        "reference": 1, "electronics": 2, "cooling": 2, "system": 4}


def test_assembly_requires_its_owned_component_claim(assembly):
    child = assembly / "electronics"
    key = "electronics::load.local_budget"
    edit_yaml(child / "project.yaml", lambda d: d["exports"].update(allocation="load.local_budget"))
    edit_yaml(child / "model/load.yaml", lambda d: d["requirements"]["local_budget"]["verify"]["limit"].update(value=50))

    def require_allocation(manifest):
        manifest.update(scope=[], children={"electronics": {"path": "electronics"}}, required_claims=["allocation"])
        manifest["imports"]["allocation"] = {"path": "electronics", "export": "allocation"}

    edit_yaml(assembly / "project.yaml", require_allocation)
    for unit in (child, assembly):
        approve_baseline(unit, "System Engineering", "Reviewed the component allocation")
    report = Engine(assembly).verify(trusted=True)
    assert report["scope"] == [key] and report["counts"] == {"FAIL": 1}
    assert not report["gates"]["electronics"]["gate"] and not report["gate"]
    assert "electronics" in report["gates"]["system"]["reasons"]
    assert report["gates"]["system"]["applicable"] == 1


def test_required_child_and_supplier_contract(assembly):
    local = assembly / "cooling/model/load.yaml"
    local.write_text(local.read_text().replace("value: 60", "value: 50"))
    report = Engine(assembly).verify(trusted=True)
    assert not report["gates"]["cooling"]["gate"] and not report["gate"]
    path = assembly / "cooling/project.yaml"
    path.write_text(path.read_text().replace("export: load", "export: secret"))
    with pytest.raises(ClosureError, match="does not export secret"):
        Project(assembly)


@pytest.fixture
def electronics_allocation(assembly):
    child = assembly / "electronics"
    edit_yaml(assembly / "project.yaml", lambda d: d.update(exports={"allocation": "budget.maximum"}))
    edit_yaml(child / "project.yaml", lambda d: d["imports"].update(allocation={"path": "..", "export": "allocation"}))
    edit_yaml(child / "model/load.yaml", lambda d: d["requirements"]["local_budget"]["verify"].update(limit={"ref": "@allocation"}))
    return child


def test_standalone_child_uses_parent_allocation_without_cooling(assembly, electronics_allocation, capsys):
    child = electronics_allocation
    edit_yaml(assembly / "model/budget.yaml", lambda d: d["parameters"].update(reserve={"value": 10, "unit": "W"}))

    def configure_parent(manifest):
        manifest["scenarios"] = {"nominal": {"overrides": {
            "budget.maximum": {"value": 100, "unit": "W"}, "budget.reserve": {"value": 12, "unit": "W"}}}}
        manifest["imports"]["fan"]["port"] = {"type": "quantity", "unit": "W"}

    edit_yaml(assembly / "project.yaml", configure_parent)
    approve_baseline(child, "Electronics engineer", "Reviewed the assembly allocation")
    shutil.rmtree(assembly / "cooling")

    assert main(["verify", "--project", str(child), "--trusted", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["gate"] and report["scope"] == ["electronics::load.local_budget"]
    assert set(report["projects"]) == {"electronics", "system", "reference"}
    assert report["executed"] == ["reference::profile.evaluate", "electronics::load.scale"]
    assert "system::budget.reserve" not in report["values"]
    comparison = next(r for r in report["requirements"] if r["id"] == "electronics::load.local_budget")["comparisons"][0]
    assert comparison["actual"] == 52 and comparison["limit"] == 100


def test_standalone_child_reports_missing_input_to_parent_calculation(assembly, electronics_allocation, capsys):
    def calculated_allocation(manifest):
        manifest["exports"]["allocation"] = "budget.sum.total"
        manifest["imports"]["reference_load"] = {"path": "reference", "export": "load"}

    edit_yaml(assembly / "project.yaml", calculated_allocation)
    edit_yaml(assembly / "model/budget.yaml", lambda d: d["analyses"]["sum"].update(valid_when=[
        {"actual": {"ref": "@reference_load"}, "op": "gt", "limit": {"value": 0, "unit": "W"}}]))
    approve_baseline(electronics_allocation, "Electronics engineer", "Reviewed the calculated allocation")
    assert main(["verify", "--project", str(electronics_allocation), "--trusted", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["gate"] and report["values"]["system::budget.sum.total"]["value"] == 104
    assert set(report["executed"]) == {
        "electronics::load.scale", "cooling::load.scale", "reference::profile.evaluate", "system::budget.sum"}
    shutil.rmtree(assembly / "cooling")

    assert main(["plan", "--project", str(electronics_allocation), "--json"]) == 2
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "MISSING_PROJECT"
    assert all(detail in error["message"] for detail in ("fan", "demand", "cooling"))
    assert Path(error["location"]) == assembly / "project.yaml"


def test_value_supplier_explains_its_unscoped_requirement_without_a_gate(assembly):
    electronics = assembly / "electronics"
    key = "electronics::load.local_budget"
    edit_yaml(assembly / "project.yaml", lambda d: d["children"].pop("electronics"))
    approve_baseline(electronics, "Electronics engineer", "Reviewed the component allocation")
    approve_baseline(assembly, "Assembly engineer", "Reviewed the supplied demand")
    component_baseline = Engine(electronics).baseline()
    engine = Engine(assembly)
    saved = engine.verify(trusted=True)
    assert saved["gate"] and "electronics" not in saved["gates"] and key not in saved["scope"]
    assert engine.explain(key)["baseline"] == component_baseline

    # Only a standalone verification of electronics needs this child project.
    edit_yaml(electronics / "project.yaml", lambda d: d.update(children={"board": {"path": "board"}}))
    current = Engine(assembly)
    report = current.verify(trusted=True, force=True)
    assert report["gate"] and "electronics::load.scale" in report["executed"]
    assert report["values"]["system::budget.sum.total"]["value"] == 104
    for explanation in (current.explain(key), explain_saved_report(report, key)):
        assert explanation["baseline_project"] == "electronics" and explanation["baseline"] is None
        assert not explanation["requirement"]["closed"]
    archived = explain_saved_report(engine.store.load_report(saved["id"]), key)
    assert archived["baseline_project"] == "electronics" and archived["baseline"] == component_baseline


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
