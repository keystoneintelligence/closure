"""End-to-end checks for the generic, four-project power example."""
import shutil
from pathlib import Path

import pytest

from closure.engine import Engine
from closure.io import ClosureError
from closure.project import Project

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
    assert changed["requirements"][0]["comparisons"][0]["margin"] == -4
    independent = Engine(assembly / "electronics").verify(trusted=True)
    assert independent["gate"] and len(independent["executed"]) == 2
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

