"""Changes to the criterion, evidence, context and policy have distinct review consequences."""
import json
import shutil
from pathlib import Path

import pytest

from closure.cli import main
from closure.engine import Engine, approve_baseline, record_review
from closure.evidence import EvidenceStore
from closure.io import ClosureError
from closure.reporting import export_report
from closure.viewer_server import Viewer
from conftest import edit_yaml


@pytest.fixture
def assembly(tmp_path):
    root = tmp_path / "assembly"
    shutil.copytree(Path(__file__).parents[1] / "examples/composed-power", root,
                    ignore=shutil.ignore_patterns(".closure", "__pycache__"))
    return root


def verify(root, **kwargs):
    return Engine(root).verify(trusted=True, **kwargs)


def approve(root):
    approve_baseline(root, "System Engineering", "Reviewed the acceptance definition")


def requirement(report, identifier):
    return next(row for row in report["requirements"] if row["id"] == identifier)


def install_allowance(root):
    model = root / "model/budget.yaml"
    def calculate(document):
        document["analyses"]["allowance"] = {
            "run": {"argv": ["python", "allowance.py"], "sources": ["allowance.py"]},
            "settings": {"watts": 100}, "outputs": {"maximum": {"type": "quantity", "unit": "W"}}}
        document["requirements"]["power"]["verify"]["limit"] = {"ref": "budget.allowance.maximum"}
    edit_yaml(model, calculate)
    (root / "allowance.py").write_text(
        'import json, sys\nfrom calibration import offset\nr=json.load(sys.stdin)\n'
        'print(json.dumps({"protocol":r["protocol"], "invocation_id":r["invocation_id"], '
        '"outputs":{"maximum":{"value":r["settings"]["watts"]+offset, "unit":"W"}}}))\n')
    (root / "calibration.py").write_text("offset = 0\n")
    return model


def test_calculated_allowance_and_actual_change_independently(assembly, tmp_path, capsys):
    key = "system::budget.power"
    model = install_allowance(assembly)
    approve(assembly)
    failed = verify(assembly)
    assert failed["baseline"]["status"] == "current" and requirement(failed, key)["verdict"] == "fail"
    # A performance improvement closes against the same 100 W approval.
    reference = assembly / "reference/model/load.yaml"
    edit_yaml(reference, lambda d: d["parameters"]["reference"].update(value=24.5))
    improved = verify(assembly)
    assert improved["gate"] and requirement(improved, key)["comparisons"][0]["actual"] == 98
    assert "system::budget.allowance" not in improved["executed"]
    edit_yaml(reference, lambda d: d["parameters"]["reference"].update(value=26))
    verify(assembly)
    edit_yaml(model, lambda d: d["analyses"]["allowance"]["settings"].update(watts=110))
    assert Engine(assembly).plan()["baseline"]["status"] == "changed"
    assert main(["verify", "--project", str(assembly), "--trusted"]) == 1
    assert "watts" in capsys.readouterr().out
    report = json.loads((assembly / ".closure/report.json").read_bytes())
    row = requirement(report, key)
    assert row["verdict"] == "pass" and row["status"] == "REVIEW" and not report["gate"]
    assert report["executed"] == ["system::budget.allowance"]
    assert any("100 W to 110 W" in line for line in report["comparison"]["changes"])
    assert Viewer(assembly, assembly).snapshot(report_id=report["id"])["report"] == report
    export_report(assembly, tmp_path / "proposal", report["id"])
    assert "watts" in (tmp_path / "proposal/index.html").read_text(encoding="utf-8")
    approve(assembly)
    accepted = verify(assembly)
    assert accepted["gate"] and accepted["executed"] == []
    (assembly / "notes.txt").write_text("Unrelated design notes")
    assert verify(assembly)["gate"]
    # A formula edit can change meaning even if its output happens to stay at 110 W.
    (assembly / "calibration.py").write_text("offset = 3 - 3\n")
    formula = verify(assembly)
    assert not formula["gate"] and formula["executed"] == ["system::budget.allowance"]
    assert any("calibration.py changed" in line for line in formula["baseline_changes"])
    (assembly / "allowance.py").unlink()
    assert not verify(assembly)["gate"]
    with pytest.raises(ClosureError, match="Source not found"):
        approve(assembly)
    assert EvidenceStore(assembly).load_report(accepted["id"])["gate"]


def require_review(root, child):
    unit = root / child
    edit_yaml(unit / "model/load.yaml", lambda d: d["requirements"]["local_budget"].update(review_required=True))
    approve(unit)
    return unit


def review_child(unit, decision="accepted", name="Morgan"):
    key = unit.name + "::load.local_budget"
    return record_review(Engine(unit), key, decision, name, "Reviewed the component evidence")


def test_two_child_approvals_survive_linking_and_parent_policy(assembly, tmp_path, capsys):
    children = [require_review(assembly, name) for name in ("electronics", "cooling")]
    approve(assembly)
    originals = {}
    for i, unit in enumerate(children):
        report = verify(unit)
        assert not report["gate"]
        assert len(report["executed"]) == (2 if i == 0 else 1)
        review = review_child(unit, name=unit.name + " engineer")
        row = requirement(verify(unit), review["requirement"])
        originals[row["id"]] = (row["evidence"], row["review"])
    assert main(["verify", "--project", str(assembly), "--trusted"]) == 0
    assert "electronics engineer" in capsys.readouterr().out
    parent = json.loads((assembly / ".closure/report.json").read_bytes())
    assert parent["executed"] == ["system::budget.sum"] and parent["gate"]
    for key, (evidence, review) in originals.items():
        row = requirement(parent, key)
        assert row["evidence"] == evidence and row["review"] == review
        assert EvidenceStore(assembly).load_run(evidence[0])["id"] == evidence[0]
    # A change to a sibling's code reopens only that sibling's review.
    source = children[1] / "scale.py"
    old = source.read_bytes()
    source.write_bytes(old + b"\n# revised model\n")
    changed = verify(assembly)
    assert not changed["gate"] and changed["gates"]["electronics"]["gate"]
    assert requirement(changed, "cooling::load.local_budget")["review"] is None
    source.write_bytes(old)
    assert verify(assembly)["gate"]
    edit_yaml(assembly / "project.yaml", lambda d: d.update(policy={"accepted_evidence": ["measured"]}))
    approve(assembly)
    rejected = verify(assembly)
    row = requirement(rejected, "electronics::load.local_budget")
    assert rejected["executed"] == [] and not rejected["gate"]
    assert row["status"] == "REJECTED" and row["review"]["reviewer"] == "electronics engineer"
    # The portable report remains self-contained after the owner's entire store is gone.
    for unit in children:
        shutil.rmtree(unit / ".closure")
    export_report(assembly, tmp_path / "archive", parent["id"])
    html = (tmp_path / "archive/index.html").read_text(encoding="utf-8")
    assert all(name in html for name in ("electronics engineer", "cooling engineer", "Reviewed the component evidence"))


def test_forced_child_run_reopens_parent_even_when_output_matches(assembly):
    child = require_review(assembly, "electronics")
    approve(assembly)
    verify(child)
    review_child(child)
    first = verify(assembly)
    assert first["gate"]
    verify(child, force=True)
    second = verify(assembly)
    key = "electronics::load.local_budget"
    assert not second["gate"] and requirement(second, key)["review"] is None
    assert requirement(first, key)["comparisons"] == requirement(second, key)["comparisons"]
    assert requirement(first, key)["evidence"] != requirement(second, key)["evidence"]
    review_child(child)
    assert verify(assembly)["gate"]


def test_legacy_child_and_intermediate_review_authorities(assembly):
    # A 0.1 child has local IDs in sealed records. Composing it must preserve those records.
    legacy = assembly / "electronics/legacy"
    shutil.copytree(Path(__file__).parents[1] / "src/closure/templates/power", legacy)
    edit_yaml(legacy / "project.yaml", lambda d: d.update(project="legacy"))
    edit_yaml(legacy / "model/power.yaml", lambda d: d["requirements"]["PWR-001"].update(review_required=True))
    edit_yaml(assembly / "electronics/project.yaml", lambda d: d.update(children={"legacy": {"path": "legacy"}}))
    for root in (legacy, assembly / "electronics", assembly):
        approve(root)
    native = verify(legacy)
    key = "legacy::power.PWR-001"
    review = record_review(Engine(legacy), "power.PWR-001", "accepted", "Lee", "Checked the native power run")
    parent = verify(assembly)
    row = requirement(parent, key)
    assert parent["gate"] and row["review"]["at"] == review["at"]
    assert row["evidence"] == requirement(native, "power.PWR-001")["evidence"]
    assert "legacy::power.budget" not in parent["executed"]
    record_review(Engine(assembly / "electronics"), key, "rejected", "Sam", "Hold this assembly")
    record_review(Engine(legacy), "power.PWR-001", "accepted", "Lee", "Local calculation checked again")
    held = Engine(assembly).plan()
    assert not held["gate"] and requirement(held, key)["review"]["reviewer"] == "Sam"
    record_review(Engine(assembly / "electronics"), key, "accepted", "Sam", "Hold cleared")
    assert verify(assembly)["gate"]


def test_child_review_is_specific_to_inputs_and_context(assembly):
    child = require_review(assembly, "electronics")
    for manifest in assembly.rglob("project.yaml"):
        edit_yaml(manifest, lambda d: d.update(configurations={"default": {}, "alternate": {}}))
    for path in (child, assembly / "cooling", assembly):
        approve(path)
    verify(child)
    review_child(child)
    assert verify(assembly)["gate"]
    alternate = Engine(assembly, configuration="alternate").verify(trusted=True)
    key = "electronics::load.local_budget"
    assert not alternate["gate"] and requirement(alternate, key)["review"] is None
    reference = assembly / "reference/model/load.yaml"
    edit_yaml(reference, lambda d: d["parameters"]["reference"].update(value=25))
    changed = verify(assembly)
    assert requirement(changed, key)["verdict"] == "pass"
    assert not changed["gate"] and requirement(changed, key)["review"] is None


def test_parent_cannot_apply_a_review_to_a_different_passing_alternative(assembly):
    import copy
    child = require_review(assembly, "electronics")
    def alternatives(d):
        d["analyses"]["observed"] = copy.deepcopy(d["analyses"]["scale"])
        d["analyses"]["observed"]["evidence_class"] = "measured"
        req = d["requirements"]["local_budget"]
        first = req["verify"]
        second = copy.deepcopy(first)
        second["actual"]["ref"] = "load.observed.demand"
        req["verify"] = {"any_of": [first, second]}
    edit_yaml(child / "model/load.yaml", alternatives)
    edit_yaml(child / "project.yaml", lambda d: d.update(policy={"accepted_evidence": ["predicted", "measured"]}))
    edit_yaml(assembly / "project.yaml", lambda d: d.update(policy={"accepted_evidence": ["measured"]}))
    approve(child)
    approve(assembly)
    verify(child)
    review_child(child)
    key = "electronics::load.local_budget"
    assert requirement(Engine(child).plan(), key)["selected_branches"] == [0]
    row = requirement(verify(assembly), key)
    assert row["selected_branches"] == [1] and row["status"] == "REVIEW" and row["review"] is None


def test_failed_forced_attempt_withdraws_owner_evidence_in_both_scopes(assembly, monkeypatch):
    child = require_review(assembly, "electronics")
    approve(assembly)
    verify(child)
    review_child(child)
    original = verify(assembly)
    assert original["gate"]
    execute = EvidenceStore.execute
    def fail_component(self, project, identifier, *args):
        if identifier == "electronics::load.scale":
            raise ClosureError("Transient instrument error", "RUN_ERROR")
        return execute(self, project, identifier, *args)
    monkeypatch.setattr(EvidenceStore, "execute", fail_component)
    assert not verify(child, force=True)["gate"]
    for root in (assembly, child):
        row = requirement(Engine(root).plan(), "electronics::load.local_budget")
        assert not row["closed"] and row["review"] is None
    assert EvidenceStore(assembly).load_report(original["id"])["gate"]


def test_legacy_baseline_omitting_formula_needs_one_review(assembly):
    from closure.io import atomic_json, digest
    install_allowance(assembly)
    approved = approve_baseline(assembly, "Engineer", "Original approval")
    del approved["contract"]["limit_calculations"]
    approved["contract_hash"] = digest(approved["contract"])
    atomic_json(assembly / "reviews/baseline.json", approved)
    plan = Engine(assembly).plan()
    assert plan["baseline"]["status"] == "changed"
    assert any("system::budget.allowance" in line for line in plan["baseline_changes"])
    approve(assembly)
    assert Engine(assembly).plan()["baseline"]["status"] == "current"


def test_reviewed_artifacts_export_before_and_after_root_verify(assembly, tmp_path):
    child = require_review(assembly, "electronics")
    edit_yaml(child / "model/load.yaml", lambda d: d["analyses"]["scale"]["outputs"].update(
        notes={"type": "artifact"}))
    source = child / "scale.py"
    code = source.read_text()
    code = code.replace('print(json.dumps(', 'from pathlib import Path\n'
                        'out=Path(request["output_dir"])/"notes.txt"\nout.write_text("component observation")\n'
                        'print(json.dumps(').replace('"outputs": {', '"outputs": {"notes":{"path":str(out)},')
    source.write_text(code)
    approve(assembly)
    verify(child)
    review_child(child)
    key = "electronics::load.local_budget"
    live = Engine(assembly)
    record_id = requirement(live.plan(), key)["evidence"][0]
    assert not (assembly / ".closure").exists()
    export_report(live, tmp_path / "planned")
    saved = verify(assembly)
    assert saved["gate"] and requirement(saved, key)["evidence"] == [record_id]
    record = EvidenceStore(assembly).load_run(record_id)
    archive = EvidenceStore(child).artifact_path(record["outputs"]["notes"])
    archive.write_text("changed bytes")
    assert not requirement(Engine(assembly).plan(), key)["closed"]
    export_report(assembly, tmp_path / "sealed", saved["id"])
    for bundle in ("sealed", "planned"):
        assert next((tmp_path / bundle / "artifacts").glob("*-notes.txt")).read_text() == "component observation"
    # New evidence repairs the owner's archive, but the previous review stays bound to its original run.
    refreshed = verify(assembly)
    assert not refreshed["gate"] and requirement(refreshed, key)["review"] is None


def test_read_only_supplier_can_be_linked_and_rebuilt_locally(assembly, monkeypatch):
    import os
    child = require_review(assembly, "electronics")
    approve(assembly)
    verify(child)
    review_child(child)
    access = os.access
    monkeypatch.setattr(os, "access", lambda path, mode: False if path == child / ".closure" else access(path, mode))
    first = verify(assembly)
    key = "electronics::load.local_budget"
    assert first["gate"] and "electronics::load.scale" not in first["executed"]
    forced = verify(assembly, force=True)
    assert not forced["gate"] and requirement(forced, key)["review"] is None
    assert requirement(Engine(assembly).plan(), key)["evidence"] == requirement(forced, key)["evidence"]


def test_replacing_declared_limit_tool_reopens_approval(assembly, tmp_path, monkeypatch):
    import sys
    model = install_allowance(assembly)
    edit_yaml(model, lambda d: d["analyses"]["allowance"]["run"].update(tools={"calibrator": "python"}))
    tool = tmp_path / Path(sys.executable).name
    shutil.copy2(sys.executable, tool)
    monkeypatch.setenv("CLOSURE_TOOL_CALIBRATOR", str(tool))
    approve(assembly)
    assert Engine(assembly).plan()["baseline"]["status"] == "current"
    with tool.open("ab") as f:
        f.write(b"revision two")
    plan = Engine(assembly).plan()
    assert plan["baseline"]["status"] == "changed"
    assert any("executable calibrator changed" in line for line in plan["baseline_changes"])


def test_nested_limit_files_inputs_and_validity_are_baselined(assembly):
    model = install_allowance(assembly)
    def wire(d):
        d["parameters"]["data"] = {"type": "artifact", "path": "curve.txt"}
        d["parameters"]["mode"] = {"value": True}
        d["analyses"]["calibration"] = {
            "run": {"argv": ["python", "curve.py"], "sources": ["curve.py"], "tool_files": ["tool.cfg"]},
            "inputs": {"curve": {"ref": "budget.data"}},
            "valid_when": [{"actual": {"ref": "budget.mode"}, "op": "eq", "limit": {"value": True}}],
            "outputs": {"rating": {"type": "quantity", "unit": "W"}}}
        d["analyses"]["allowance"]["inputs"] = {"calibration": {"ref": "budget.calibration.rating"}}
    edit_yaml(model, wire)
    (assembly / "curve.py").write_text(
        'import json,sys\nfrom pathlib import Path\nr=json.load(sys.stdin)\n'
        'value=float(Path(r["inputs"]["curve"]["path"]).read_text())\n'
        'print(json.dumps({"protocol":r["protocol"],"invocation_id":r["invocation_id"],'
        '"outputs":{"rating":{"value":value,"unit":"W"}}}))\n')
    source = assembly / "allowance.py"
    source.write_text(source.read_text().replace('+offset', '+offset+r["inputs"]["calibration"]["value"]'))
    (assembly / "curve.txt").write_text("10")
    (assembly / "tool.cfg").write_text("v1")
    approve(assembly)
    first = verify(assembly)
    assert first["gate"]
    with pytest.raises(ClosureError, match="requirement limits"):
        Engine(assembly, overrides={"system::budget.mode": {"value": False}})
    for name, changed in (("curve.txt", "11"), ("tool.cfg", "v2")):
        file = assembly / name
        original = file.read_bytes()
        file.write_text(changed)
        altered = verify(assembly)
        assert altered["baseline"]["status"] == "changed" and not altered["gate"]
        assert set(altered["executed"]) == {"system::budget.calibration", "system::budget.allowance"}
        assert any(name in line for line in altered["baseline_changes"])
        file.write_bytes(original)
        assert verify(assembly)["gate"]
    (assembly / "curve.txt").unlink()
    assert not verify(assembly)["gate"]
    with pytest.raises(ClosureError, match="Missing limit input"):
        approve(assembly)
