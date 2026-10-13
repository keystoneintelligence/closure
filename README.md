# Closure

Engineering evidence you can follow.

Closure connects requirements, inputs, analyses and results in readable project files. Change an input and press **Verify**: affected analyses rerun, outputs propagate, and each requirement shows the evidence behind its result.

This is the **0.1.0a1 early release candidate**. Keystone Intelligence LLC develops Closure as a general-purpose engineering tool. The examples cover service capacity, electrical power, mission analysis and mechanical design.

## Three ways to use Closure

| Product | Start here |
| --- | --- |
| Closure 0.1 specification | [Implemented preview specification](spec/0.1/SPECIFICATION.md), [schemas](schema/README.md), [conformance fixtures](conformance/README.md) |
| Reference CLI and backend | [Quickstart](docs/QUICKSTART.md), [CLI guide](docs/CLI_GUIDE.md), [runner guide](docs/ENGINE_GUIDE.md) |
| Local project viewer | [Viewer guide](docs/VIEWER_GUIDE.md), [local API](docs/VIEWER_API.md) |

The specification is language-neutral at the runner boundary. The reference implementation is Python; runners can be ordinary programs in any language. The optional viewer is bundled in the same wheel and uses the same backend.

## Try the candidate

Use Python 3.10 or 3.12 on Windows or Linux. In an activated virtual environment, download the wheel from the [v0.1.0a1 release](https://github.com/keystoneintelligence/closure/releases/tag/v0.1.0a1) and install it:

```sh
python -m pip install ./closure_se-0.1.0a1-py3-none-any.whl
closure --version
closure help verify
closure init -p my-project
cd my-project
closure check
closure approve-baseline --reviewer "Your name" --reason "Reviewed the starter obligations"
closure verify --trusted
closure serve --trusted
```

Read the starter's analysis before authorizing execution. Open the localhost URL printed by `serve`. Edit a variable, save it, and press Verify. Results are saved as inspectable historical snapshots. The [quickstart](docs/QUICKSTART.md) walks through a deliberate failure and recovery.

`closure plan` shows what needs to run. `closure set` preserves types, units and metadata. `closure explain` traces requirement support. `--json` supports automation, while human results go to stdout and progress/errors to stderr. Exit 1 means an open gate; exit 2 means invalid input/setup. `closure help COMMAND` includes examples, and `closure completion bash` or `closure completion powershell` enables shell completion.

Source files use concise YAML or JSON. `closure format` removes redundant defaults while preserving model meaning. Shared engineering values belong in declared inputs and outputs, with explanations for assumptions. See the [authoring standard](docs/AUTHORING_STANDARD.md).

## Development

From the source archive or repository, in an activated environment:

```sh
python -m pip install -e ".[dev,mission]"
npm --prefix frontend ci
npm --prefix frontend run build
python -m pytest -q --ignore=tests/test_pen.py
npm --prefix frontend test
```

The prebuilt viewer is included; Node is needed only for frontend development and JavaScript conformance checks. CAD and external-tool examples need their documented optional dependencies. See [contributing](CONTRIBUTING.md), [release preparation](docs/RELEASE.md), and the [changelog](CHANGELOG.md).

## Preview scope

Verify assesses declared dependencies, model validity, selected contexts and acceptance policy. It does not establish that a physical model is correct. Execution is trusted and local; the viewer is not a hosted execution service. Review provenance is not authenticated signing. The Python numeric digest profile has explicit cross-language limits. See [compatibility](docs/COMPATIBILITY.md), [security](SECURITY.md) and the specification for the precise boundaries.

The [Closure 0.1 specification](spec/0.1/SPECIFICATION.md) defines the format and behavior for this release.

Copyright 2026 Keystone Intelligence LLC. [Apache-2.0](LICENSE). The viewer includes Three.js under its MIT license; see [third-party notices](THIRD_PARTY_NOTICES.md).

[Keystone Intelligence](https://www.keystoneintelligence.ai/) · [Source and issues](https://github.com/keystoneintelligence/closure)
