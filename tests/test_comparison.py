import subprocess
import shutil
from pathlib import Path

import pytest

from closure.comparison import compare_git
from closure.project import Project
from closure.io import ClosureError
from conftest import edit_yaml


@pytest.fixture
def committed(project_dir):
    def git(*args):
        result = subprocess.run(["git", *args], cwd=project_dir, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()
    git("init", "--quiet")
    git("add", ".")
    git("-c", "user.name=Closure test", "-c", "user.email=closure@example.invalid", "commit", "-qm", "baseline")
    return project_dir


def test_git_semantic_parameter_change_and_impact(committed):
    edit_yaml(committed / "model/payload.yaml", lambda d: d["parameters"]["peak_power"].update(value=120))
    result = compare_git(Project(committed), "HEAD")
    assert result["changes"]["parameters"][0]["before"]["value"] == 80
    assert result["changes"]["parameters"][0]["after"]["value"] == 120
    assert result["affected_analyses"] == ["power.budget"]
    assert result["affected_requirements"] == ["power.PWR-001"]
    assert not result["obligations_changed"]


def test_git_semantic_prose_review_without_numerical_rerun(committed):
    edit_yaml(committed / "model/power.yaml", lambda d: d["requirements"]["PWR-001"].update(text="New meaning"))
    result = compare_git(Project(committed), "HEAD")
    assert result["obligations_changed"]
    assert result["affected_analyses"] == []
    assert result["affected_requirements"] == ["power.PWR-001"]


def test_git_semantic_move_keeps_symbols_and_detects_source_changes(committed):
    (committed / "model/payload.yaml").rename(committed / "model/new-payload.yaml")
    moved = compare_git(Project(committed), "HEAD")
    assert moved["moved_modules"][0]["module"] == "payload"
    assert moved["affected_analyses"] == []
    script = committed / "analysis/power_budget.py"
    script.write_text(script.read_text() + "\n# A source edit changes execution identity.\n")
    result = compare_git(Project(committed), "HEAD")
    assert result["source_changes"][0]["analysis"] == "power.budget"
    assert result["affected_requirements"] == ["power.PWR-001"]
    assert not result["obligations_changed"]


def test_git_invalid_ref_is_an_error_not_an_empty_comparison(committed):
    with pytest.raises(ClosureError) as exc:
        compare_git(Project(committed), "missing-reference")
    assert exc.value.code == "GIT_BASE"


def test_git_nested_project_tracks_code_and_removed_obligations(committed):
    nested = committed / "engineering project"
    nested.mkdir()
    for name in ("project.yaml", "model", "analysis", "reviews", "studies"):
        source = committed / name
        if source.is_dir():
            shutil.copytree(source, nested / name)
        else:
            shutil.copy2(source, nested / name)
    subprocess.run(["git", "add", "."], cwd=committed, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Closure test", "-c", "user.email=closure@example.invalid", "commit", "-qm", "nested"],
                   cwd=committed, check=True, capture_output=True)
    script = nested / "analysis/power_budget.py"
    script.write_text(script.read_text() + "\n# Changed nested code\n")
    edit_yaml(nested / "model/power.yaml", lambda d: d.update(requirements={}))
    result = compare_git(Project(nested), "HEAD")
    assert result["source_changes"][0]["analysis"] == "power.budget"
    assert result["obligations_changed"]
    assert result["changes"]["requirements"][0]["change"] == "removed"
    assert "power.PWR-001" in result["affected_requirements"]
