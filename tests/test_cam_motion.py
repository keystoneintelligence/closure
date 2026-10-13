"""Check the mechanism's model against independently sampled crown surfaces."""
import importlib.util
from pathlib import Path

import pytest
from ruamel.yaml import YAML

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("pen_cam_profile", ROOT / "examples/pen/analysis/cam_profile.py")
cam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cam)


@pytest.fixture
def dimensions():
    source = YAML(typ="safe").load(ROOT / "examples/pen/model/mechanism.yaml")
    return {key: item["value"] for key, item in source["parameters"].items()}


def test_crown_contact_envelope_matches_direct_surface_search(dimensions):
    profile = cam.CamProfile(dimensions)
    # Compute both tooth heights independently at 2400 angular positions. A
    # prescribed rotor angle is only an input to this geometric comparison.
    for angle in (-2.6, 0, 15, 25, 60, 99):
        sampled = max(profile.crown(phi-angle) + profile.crown(phi+profile.phase)
                      for phi in (i*.025 for i in range(2400)))
        assert profile.separation(angle) == pytest.approx(sampled, abs=1e-8)


def test_contact_cycle_settles_and_converges_without_assigned_rotation(dimensions):
    profile = cam.CamProfile(dimensions)
    nominal = profile.solve(clicks=12)
    refined = profile.solve(clicks=2, axial_step=.0125, angular_step=.025)
    assert [end["state"] for end in nominal["ends"]] == ["extended", "retracted"]*6
    assert nominal["max_rotor_stroke_mm"] == pytest.approx(refined["max_rotor_stroke_mm"], abs=.01)
    assert 4.8 < nominal["max_rotor_stroke_mm"] < 5
    assert nominal["ends"][0]["rotor_deg"] == pytest.approx(60, abs=.1)
    assert 120 < nominal["ends"][1]["rotor_deg"] < 126  # free guide backlash is preserved
    assert nominal["ends"][0]["button_mm"] == pytest.approx(3, abs=.01)
    assert len({round(p["rotor_deg"], 1) for p in nominal["samples"]}) > 50


@pytest.mark.parametrize("change", [{"full_stroke": 4.85}, {"phase_offset": 0}, {"slot_width": 1.2}])
def test_infeasible_cam_geometry_cannot_produce_a_supported_cycle(dimensions, change):
    with pytest.raises(ValueError):
        cam.CamProfile(dimensions | change).solve()


def test_geometrically_constructible_but_misphased_crown_does_not_alternate(dimensions):
    motion = cam.CamProfile(dimensions | {"phase_offset": 15}).solve(clicks=2)
    assert [end["state"] for end in motion["ends"]] == ["unsettled", "unsettled"]
