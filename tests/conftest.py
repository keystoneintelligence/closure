import shutil
from pathlib import Path
import pytest
from ruamel.yaml import YAML
from closure.engine import approve_baseline
from closure.project import Project


@pytest.fixture
def project_dir(tmp_path):
    source = Path(__file__).parents[1] / "src" / "closure" / "templates" / "power"
    shutil.copytree(source, tmp_path, dirs_exist_ok=True)
    approve_baseline(Project(tmp_path), "test reviewer", "Approve the independent RFC fixture")
    return tmp_path


def edit_yaml(path, update):
    parser = YAML(typ="rt")
    value = parser.load(path.read_text(encoding="utf-8"))
    update(value)
    with path.open("w", encoding="utf-8") as stream:
        parser.dump(value, stream)


def runner(path, body, outputs=None):
    (path / "analysis" / "power_budget.py").write_text(
        "import json, sys, pathlib\nr = json.load(sys.stdin)\n" + body + "\n", encoding="utf-8")
    if outputs:
        edit_yaml(path / "model" / "power.yaml", lambda d: d["analyses"]["budget"].update(outputs=outputs))
