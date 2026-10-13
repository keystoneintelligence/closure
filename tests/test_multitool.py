"""Opt-in test of the installed applications, not simulated tool responses."""
import json
import math
import os
import re
import shutil
import zipfile
from pathlib import Path

import pytest

from closure.engine import Engine
from closure.evidence import EvidenceStore
from conftest import edit_yaml


@pytest.mark.skipif(os.environ.get("CLOSURE_RUN_EXTERNAL_TOOLS") != "1",
                    reason="Set CLOSURE_RUN_EXTERNAL_TOOLS=1 with Blender and WSL OpenFOAM installed")
def test_real_blender_python_openfoam_chain_and_geometry_change(tmp_path, monkeypatch):
    source = Path(__file__).parents[1] / "examples/multitool"
    shutil.copytree(source, tmp_path, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".closure", "deliverables", "last-build.json"))
    first = Engine(tmp_path).build(trusted=True)
    assert first["gate"], [(a["id"], a["error"]) for a in first["analyses"]]
    assert set(first["executed"]) == {"geometry.export", "physics.scaling", "fluid.cavity"}
    store = EvidenceStore(tmp_path)
    diagnostics = json.loads(store.artifact_path(first["values"]["fluid.cavity.diagnostics"]).read_text())
    geometry = json.loads(store.artifact_path(first["values"]["geometry.export.inspection"]).read_text())
    assert geometry["blender_version"] and geometry["source_object"] == "FluidDomain"
    assert first["values"]["geometry.export.length"]["value"] == pytest.approx(0.1)
    assert first["values"]["physics.scaling.reynolds"]["value"] == pytest.approx(100)
    assert diagnostics["cells"] == 400 and diagnostics["final_time_s"] == 1
    assert 0 < diagnostics["max_courant"] <= 0.5
    assert diagnostics["max_linear_final_residual"] < 1e-5
    assert 0.5 < diagnostics["maximum_internal_velocity_m_s"] < 1
    # Independently read the actual field and retained solver log from the case.
    with zipfile.ZipFile(store.artifact_path(first["values"]["fluid.cavity.case"])) as archive:
        field = archive.read("1/U").decode()
        interior = re.search(r"internalField\s+nonuniform\s+List<vector>\s+400\s*\((.*?)\)\s*;", field, re.S)
        assert interior
        vectors = [list(map(float, row.split())) for row in re.findall(r"\(([^()]+)\)", interior[1])]
        assert len(vectors) == 400 and all(len(v) == 3 and all(map(math.isfinite, v)) for v in vectors)
        assert sum(v[0] < 0 for v in vectors) == diagnostics["negative_x_cells"] > 0
        log = archive.read("logs/icoFoam.log").decode()
        assert "OpenFOAM" in log and len(re.findall(r"^Time =", log, re.M)) == 500
        assert "Mesh OK." in archive.read("logs/checkMesh.log").decode()
    edit_yaml(tmp_path / "model/geometry.yaml", lambda d: d["parameters"]["length"].update(value=0.08))
    assert not Engine(tmp_path).plan()["gate"]
    second = Engine(tmp_path).build(trusted=True)
    assert second["gate"], [(a["id"], a["error"]) for a in second["analyses"]]
    assert second["values"]["geometry.export.length"]["value"] == pytest.approx(0.08)
    assert second["values"]["physics.scaling.reynolds"]["value"] == pytest.approx(80)
    with zipfile.ZipFile(store.artifact_path(second["values"]["fluid.cavity.case"])) as archive:
        assert float(re.search(r"^L (.*?);", archive.read("closureParameters").decode(), re.M)[1]) == pytest.approx(0.08)
    assert first["analyses"][0]["record"]["id"] != second["analyses"][0]["record"]["id"]
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("Read-only inspection launched a tool"))
    assert not Engine(tmp_path).plan()["gate"]  # Unisolated tool runtimes must not reuse their cache.
    assert store.load_report(first["id"])["values"]["geometry.export.length"]["value"] == pytest.approx(0.1)
