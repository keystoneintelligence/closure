"""Plan and run the service-capacity example under its declared operating contexts."""
import json

import pytest

from closure.cli import main
from closure.evidence import EvidenceStore
from conftest import edit_yaml
from test_general_projects import service


CAPACITY = "service-capacity::platform.capacity"
ENERGY = "service-capacity::platform.energy"
HEADROOM = "service-capacity::operations.CAP-001"


@pytest.fixture
def cli(service, capsys):
    edit_yaml(service / "project.yaml", lambda d: d.update(schema="closure/0.2"))
    edit_yaml(service / "model/operations.yaml", lambda d: d["requirements"]["CAP-001"].update(
        applies_to=["surge"], configurations=["expanded"]))

    def invoke(*args):
        code = main([*args, "--project", str(service), "--json"])
        output = capsys.readouterr()
        result = json.loads(output.out)
        assert code == 0, result.get("error") or result.get("gates") or output.err
        return result

    return invoke


@pytest.fixture
def executions(monkeypatch):
    calls = []
    execute = EvidenceStore.execute

    def record(store, project, identifier, *args, **kwargs):
        calls.append(identifier)
        return execute(store, project, identifier, *args, **kwargs)

    monkeypatch.setattr(EvidenceStore, "execute", record)
    return calls


def approve_headroom_exclusion(cli, context):
    cli("approve-baseline", "--reviewer", "Reliability engineering", "--reason", "Reviewed service criteria")
    return cli("review", HEADROOM, "--decision", "not_applicable", "--reviewer", "Reliability engineering",
               "--reason", "Headroom criterion applies to the expanded surge configuration", *context)


def headroom(report):
    return next(row for row in report["requirements"] if row["id"] == HEADROOM)


@pytest.mark.parametrize("scenario,configuration", [("routine", "expanded"), ("surge", "balanced")])
def test_energy_budget_runs_without_capacity_model(cli, executions, scenario, configuration):
    context = ["--scenario", scenario, "--configuration", configuration]
    review = approve_headroom_exclusion(cli, context)
    plan = cli("plan", *context)
    assert [row["id"] for row in plan["analyses"] if row["will_run"]] == [ENERGY]
    assert headroom(plan)["review"] == review and executions == []

    for flags in ([], ["--force"]):
        executions.clear()
        report = cli("verify", "--trusted", *flags, *context)
        assert report["gate"] and report["executed"] == executions == [ENERGY]
        assert headroom(report)["status"] == "NOT_APPLICABLE" and headroom(report)["review"] == review

    executions.clear()
    for report in (cli("plan", *context), cli("verify", "--trusted", *context)):
        assert report["gate"] and report["executed"] == executions == []
        assert headroom(report)["review"] == review

    expanded = ["--scenario", "surge", "--configuration", "expanded"]
    executions.clear()
    plan = cli("plan", *expanded)
    work = [row["id"] for row in plan["analyses"] if row["will_run"]]
    assert work == [CAPACITY, ENERGY] and executions == []
    report = cli("verify", "--trusted", *expanded)
    assert report["gate"] and report["executed"] == executions == work
    assert headroom(report)["status"] == "PASS"


@pytest.mark.parametrize("check_utilization", [False, True], ids=["transitive", "shared"])
def test_power_model_validity_requires_one_capacity_run(service, cli, executions, check_utilization):
    utilization = {"actual": {"ref": "platform.capacity.utilization"}, "op": "lte",
                   "limit": {"value": 100, "unit": "percent"}}
    edit_yaml(service / "model/platform.yaml", lambda d: d["analyses"]["energy"].update(valid_when=[utilization]))
    if check_utilization:
        edit_yaml(service / "model/operations.yaml", lambda d: d["requirements"].update({
            "UTIL-001": {"text": "Serving workers shall remain within throughput capacity.",
                         "applies_to": ["routine"], "configurations": ["balanced"], "verify": utilization}}))

    context = ["--scenario", "routine", "--configuration", "balanced"]
    review = approve_headroom_exclusion(cli, context)
    plan = cli("plan", *context)
    work = [row["id"] for row in plan["analyses"] if row["will_run"]]
    assert work == [CAPACITY, ENERGY] and executions == []
    report = cli("verify", "--trusted", *context)
    assert report["gate"] and report["executed"] == executions == work
    assert headroom(report)["status"] == "NOT_APPLICABLE" and headroom(report)["review"] == review
