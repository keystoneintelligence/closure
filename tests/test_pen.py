"""Real CAD and cross-team evidence tests for the engineering demonstrator."""
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from closure.editing import patch_parameters
from closure.engine import Engine
from closure.project import Project


@pytest.fixture(scope="module")
def pen(tmp_path_factory):
    pytest.importorskip("cadquery")
    pytest.importorskip("trimesh")
    root = tmp_path_factory.mktemp("pen")
    shutil.copytree(Path(__file__).parents[1] / "examples/pen", root,
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns(".closure", "deliverables", "__pycache__"))
    patch_parameters(root, Project(root).source_hash, {"spring.wire": {"value": .45, "unit": "mm"}})
    report = Engine(root).build(trusted=True)
    assert report["gate"], [(a["id"], a["error"]) for a in report["analyses"]]
    return root, report


def test_pen_has_real_geometry_and_mass_evidence(pen):
    import cadquery as cq
    import trimesh
    root, report = pen
    values = report["values"]
    cad = lambda name: Path(values[f"manufacturing.cad.{name}"]["path"])
    solids = cq.importers.importStep(str(cad("step"))).solids().vals()
    assert len(solids) == 10
    assert all(s.isValid() and s.Volume() > 0 for s in solids)
    scene = trimesh.load(str(cad("model")), file_type="glb")
    assert len(scene.geometry) == 10
    assert scene.bounds[1][2] - scene.bounds[0][2] == pytest.approx(.1405, abs=.0001)
    manifest = json.loads(cad("assembly").read_text())
    part_ids = {p["id"] for p in manifest["parts"]}
    assert {"refill", "spring", "rotor", "button", "cam_sleeve", "barrel", "nose", "cap", "spring_seat", "spring_guide"} == part_ids
    with zipfile.ZipFile(cad("stl_parts")) as archive:
        assert set(archive.namelist()) == {p + ".stl" for p in part_ids}
    with zipfile.ZipFile(cad("native_parts")) as archive:
        assert set(archive.namelist()) == {p + ".brep" for p in part_ids}
    assert len(manifest["actuation"]["transitions"]) == 3
    assert all(len(t["keyframes"]) > 100 for t in manifest["actuation"]["transitions"])
    # Independent quantity check against actual CAD volumes, not the BOM's total.
    densities = {"aluminum": 2.7, "acetal": 1.42, "steel": 7.85}
    expected_mass = sum(p["volume_mm3"] * densities[p["material"]] / 1000
                        for p in manifest["parts"] if p["material"] in densities) + 3
    assert values["manufacturing.materials.mass"]["value"] == pytest.approx(expected_mass)
    assert 17 < expected_mass < 22


def test_pen_closes_declared_analytical_scope_and_keeps_tests_open(pen):
    root, report = pen
    assert len(Project(root).modules) == 8
    assert all(r["closed"] for r in report["requirements"] if r["scoped"])
    physical = [r for r in report["requirements"] if r["id"].startswith("verification.TEST")]
    assert len(physical) == 3
    assert all(not r["closed"] and r["status"] == "MISSING" for r in physical)
    values = report["values"]
    assert 2.65 < values["mechanism.kinematics.push_force"]["value"] < 2.67
    assert values["spring.response.safety_factor"]["value"] > 1.5
    assert values["barrel.strength.safety_factor"]["value"] > 3
    assert values["manufacturing.contacts.valid"]["value"] is True
    audit = json.loads(Path(values["manufacturing.contacts.audit"]["path"]).read_text())
    assert audit["sample_count"] > 150 and audit["overlaps"] == []
    assert audit["all_connected_valid"] and audit["maximum_intersection_mm3"] <= .001
    assert {p["click"] for p in audit["samples"]} == {1, 2, 3}


def test_pen_spring_change_breaks_cross_team_closure_then_restores_it(pen):
    root, baseline = pen
    patch_parameters(root, Project(root).source_hash, {"spring.wire": {"value": .55, "unit": "mm"}})
    stale = Engine(root).plan()
    assert next(r for r in stale["requirements"] if r["id"] == "mechanism.MEC-001")["status"] == "STALE"
    assert next(a for a in stale["analyses"] if a["id"] == "barrel.strength")["state"] == "current"
    regression = Engine(root).build(trusted=True)
    assert not regression["gate"]
    assert regression["values"]["mechanism.kinematics.push_force"]["value"] > 5
    assert next(r for r in regression["requirements"] if r["id"] == "mechanism.MEC-001")["verdict"] == "fail"
    paths = Engine(root).explain("mechanism.MEC-001")["paths"]
    assert any(p[0] == "spring.wire" and "spring.response" in p and "mechanism.kinematics" in p for p in paths)
    patch_parameters(root, Project(root).source_hash, {"spring.wire": {"value": .45, "unit": "mm"}})
    restored = Engine(root).build(trusted=True)
    assert restored["gate"] and restored["executed"] == []
