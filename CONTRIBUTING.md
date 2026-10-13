# Contributing to Closure

This is the `0.1.0a1` public-preview candidate. Review the [implemented specification](spec/0.1/SPECIFICATION.md), [CLI guide](docs/CLI_GUIDE.md), and [compatibility policy](docs/COMPATIBILITY.md) before changing contracts.

Use a Python 3.10 or 3.12 virtual environment and Node 22 or newer:

```sh
python -m pip install -e ".[dev,mission,release]"
npm --prefix frontend ci
python -m pytest -q --ignore=tests/test_pen.py
npm --prefix frontend test
npm --prefix frontend run build
python tools/check_preview.py
```

Install browser binaries with `npm --prefix frontend exec -- playwright install chromium firefox`. Run `npm --prefix frontend run test:e2e` with the active environment's Python on PATH, or set `CLOSURE_TEST_PYTHON` to its executable. Tests use a disposable service project and do not alter the example. Linux CI additionally installs browser OS dependencies.

Keep projects general-purpose. New physics belongs in a project runner or adapter unless it changes the shared evidence model. Include a regression demonstrating changed behavior, update the specification for contract changes, regenerate schemas using `closure schema --output schema`, and rebuild the viewer after frontend changes. Generated assets and schemas are checked into release sources.

Describe the problem, resulting behavior, validation, and compatibility impact in a pull request. Use small, reviewable changes. Never include private project data, `.closure` stores, credentials, local absolute paths, or raw historical conversations. Do not weaken requirements to turn a test green. Examples and test reviewers are fictional provenance, not engineering certification.

Contributions use the same Apache-2.0 license as the project. Send proposals to [the repository](https://github.com/keystoneintelligence/closure). No separate CLA or DCO process is imposed by this preview. Specification proposals should include a minimal interoperable example and migration impact. Breaking meanings require a new protocol version; implementation bug fixes require regression tests.
