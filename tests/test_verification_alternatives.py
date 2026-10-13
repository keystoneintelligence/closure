"""Declared alternative verification paths are assessed independently."""
import copy

import pytest

from closure.engine import Engine, approve_baseline, record_review
from closure.io import ClosureError
from conftest import edit_yaml


@pytest.fixture
def alternatives(project_dir):
    original = project_dir/"analysis/power_budget.py"
    (project_dir/"analysis/alternate.py").write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
    def update(module):
        first = module["analyses"]["budget"]
        first["run"]["sources"] = ["analysis/power_budget.py"]
        second = copy.deepcopy(first)
        second["run"]["argv"][1] = "analysis/alternate.py"
        second["run"]["sources"] = ["analysis/alternate.py"]
        module["analyses"]["alternate"] = second
        requirement = module["requirements"]["PWR-001"]
        criterion = requirement["verify"]
        other = copy.deepcopy(criterion)
        other["actual"]["ref"] = "power.alternate.total"
        requirement["verify"] = {"any_of": [criterion, other]}
    edit_yaml(project_dir/"model/power.yaml", update)
    approve_baseline(project_dir, "test reviewer", "Review the two allowed verification alternatives")
    return project_dir


def requirement(report):
    return next(a for a in report["requirements"] if a["id"] == "power.PWR-001")


@pytest.mark.parametrize("unavailable", ["missing", "error"])
def test_one_supported_alternative_closes_despite_unavailable_other(alternatives, unavailable):
    other = alternatives/"analysis/alternate.py"
    if unavailable == "missing":
        other.unlink()
    else:
        other.write_text("raise RuntimeError('unavailable alternative')\n", encoding="utf-8")
    report = Engine(alternatives).build(trusted=True)
    a = requirement(report)
    assert report["gate"] and a["closed"] and a["verification_mode"] == "any_of"
    assert a["selected_branches"] == [0]
    assert a["branches"][1]["verdict"] == "unknown"
    good = next(x for x in report["analyses"] if x["id"] == "power.budget")
    assert a["evidence"] == [good["record"]["id"]]
    assert a["dependencies"] == ["power.alternate", "power.budget"]


def test_all_of_still_requires_both(alternatives):
    def all_required(module):
        plan = module["requirements"]["PWR-001"]["verify"]
        plan["all_of"] = plan.pop("any_of")
    edit_yaml(alternatives/"model/power.yaml", all_required)
    approve_baseline(alternatives, "test reviewer", "Both tests now required")
    (alternatives/"analysis/alternate.py").unlink()
    report = Engine(alternatives).build(trusted=True)
    assert not report["gate"] and requirement(report)["verdict"] == "unknown"


def predicted_only(project):
    edit_yaml(project/"project.yaml", lambda d: d["policy"].update(accepted_evidence=["predicted"]))
    edit_yaml(project/"model/power.yaml", lambda d: d["analyses"]["budget"].update(evidence_class="assumed"))
    approve_baseline(project, "test reviewer", "Require predicted evidence")


def test_allowed_passing_branch_preferred_over_disallowed_pass(alternatives):
    predicted_only(alternatives)
    report = Engine(alternatives).build(trusted=True)
    a = requirement(report)
    assert report["gate"] and a["selected_branches"] == [1]
    assert a["evidence_classes"] == ["predicted"]
    assert not a["branches"][0]["evidence_allowed"]


def fail_script(path):
    path.write_text("import json,sys\nr=json.load(sys.stdin)\nprint(json.dumps({'protocol':r['protocol'],"
                    "'invocation_id':r['invocation_id'],'outputs':{'total':{'value':300,'unit':'W'}}}))\n", encoding="utf-8")


def test_disallowed_pass_cannot_borrow_adequacy_from_failing_branch(alternatives):
    predicted_only(alternatives)
    fail_script(alternatives/"analysis/alternate.py")
    report = Engine(alternatives).build(trusted=True)
    a = requirement(report)
    assert not report["gate"] and a["verdict"] == "pass" and a["acceptance"] == "rejected"
    with pytest.raises(ClosureError, match="cannot override"):
        record_review(Engine(alternatives), a["id"], "accepted", "reviewer", "Cannot override classes")


def test_partial_failure_is_unknown_but_complete_failure_is_fail(alternatives):
    fail_script(alternatives/"analysis/power_budget.py")
    (alternatives/"analysis/alternate.py").unlink()
    partial = Engine(alternatives).build(trusted=True)
    assert not partial["gate"] and requirement(partial)["verdict"] == "unknown"
    fail_script(alternatives/"analysis/alternate.py")
    failed = Engine(alternatives).build(trusted=True)
    assert not failed["gate"] and requirement(failed)["verdict"] == "fail"
    assert requirement(failed)["freshness"] == "current"


def test_review_does_not_survive_changed_support(alternatives):
    edit_yaml(alternatives/"model/power.yaml", lambda d: d["requirements"]["PWR-001"].update(review_required=True))
    approve_baseline(alternatives, "test reviewer", "Require evidence review")
    assert not Engine(alternatives).build(trusted=True)["gate"]
    record_review(Engine(alternatives), "power.PWR-001", "accepted", "reviewer", "Reviewed passing evidence")
    assert Engine(alternatives).plan()["gate"]
    fail_script(alternatives/"analysis/power_budget.py")
    report = Engine(alternatives).build(trusted=True)
    a = requirement(report)
    assert a["selected_branches"] == [1] and a["verdict"] == "pass"
    assert not report["gate"] and a["acceptance"] == "review_required"
