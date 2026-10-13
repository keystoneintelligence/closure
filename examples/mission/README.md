# Synthetic orbital mission: eclipse energy

This example wraps the existing [SGP4 orbit propagator](https://github.com/brandon-rhodes/python-sgp4) in an ordinary JSON runner. Flight dynamics supplies a trajectory and sampled eclipse duration, payload engineering supplies its load, power engineering calculates energy demand, and mission assurance checks altitude and battery reserve. No mission-specific code is added to Closure or its viewer.

```powershell
python -m pip install -e ".[mission]"
closure check --project examples/mission
closure build --project examples/mission --trusted
closure build --project examples/mission --scenario high_load --trusted
closure explain --project examples/mission --scenario high_load operations.ENE-001
closure build --project examples/mission --scenario high_load --configuration extended --trusted
closure sweep --project examples/mission studies/energy.yaml --trusted
closure serve --project examples/mission --workspace examples --trusted
```

The high-load standard configuration and the six-point study intentionally return exit code 1. The study retains five passing designs and one failing design.

## Recorded result

For the synthetic 15.2 revolutions/day orbit, the sampled minimum altitude is approximately 496.43 km. The padded eclipse interval is 2,190 s. A 20 W payload plus 10 W bus consumes 18.25 Wh and leaves 54.375% of the assumed 40 Wh usable battery. Both preliminary criteria pass.

Increasing payload draw to 70 W leaves −21.667% reserve and fails the 20% minimum. The orbit evidence stays current; only the energy calculation reruns. Selecting the 80 Wh configuration leaves 39.167% reserve and passes. Changing orbital mean motion invalidates both the propagation and downstream energy evidence. The regression test checks this behavior and compares the SGP4 eclipse estimate with independent circular-orbit geometry.

See the recorded workflow (development record), portable baseline report (development record), and [integration test](../../tests/test_mission.py). The checked-in obligation review belongs to the example author; it is not operational approval by the user.

## Model scope

The input is synthetic, not a tracked spacecraft or a current TLE. Epoch is 2026-10-11 00:00 UTC; eccentricity 0.001 and inclination 51.6 degrees. Other initial angles and drag terms are zero. The wrapper uses SGP4's WGS72 constants and records 721 TEME states at 30 s intervals over six hours. The CSV declares position in km, velocity in km/s and the TEME frame. A fixed Sun direction along +TEME-X and a spherical, cylindrical Earth shadow approximate eclipse. The longest contiguous sampled dark interval is padded by one step at each boundary. This is a limited preliminary estimate, not a proof of all future eclipses or exact event timing.

Usable battery energy is assumed already derated. Constant electrical loads exclude charging, conversion dynamics, temperature, degradation and operational duty cycles. The 400 km altitude floor is checked only at sampled states. These assumptions and the accepted evidence classes remain visible in the project. No flight qualification is claimed.

SGP4 is an optional dependency. Ordinary core use does not require it. The `mission` extra installs it, and the CI workflow includes that extra so the integration check runs there. External-team onboarding remains an unobserved product test.

Public source archives omit development evidence stores and generated deliverables. Run Verify in your environment, then `closure export --output NEW_FOLDER` to create an inspectable report from your own run.
