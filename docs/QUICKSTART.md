# First verification

The preview has three parts: the [specification](../spec/0.1/SPECIFICATION.md), the Python reference CLI/backend, and its optional local viewer. You can write a runner in any language. Node is only needed to rebuild the viewer or run the JavaScript example; installing the wheel includes built viewer assets.

## Install the reviewed candidate

Use Python 3.10 or 3.12 on Windows or Linux. Download `closure_se-0.1.0a1-py3-none-any.whl` from the [v0.1.0a1 release assets](https://github.com/keystoneintelligence/closure/releases/tag/v0.1.0a1). The release also includes source archives, SHA-256 checksums, and a release record identifying the tested commit. From its directory:

```sh
python -m venv .venv
```

Activate with `.venv\Scripts\Activate.ps1` in PowerShell or `source .venv/bin/activate` in Bash, then:

```sh
python -m pip install ./closure_se-0.1.0a1-py3-none-any.whl
closure --version
closure help verify
closure init -p my-project
cd my-project
closure check
```

The neutral starter contains one illustrative input, an ordinary Python program and a requirement. Read the YAML and analysis before executing it. Record an explicit review of the starter obligations:

```sh
closure approve-baseline --reviewer "Your name" --reason "Reviewed the illustrative starter obligations"
closure verify --trusted
closure set system.allocation 1.2 --reason "Try a design above the example budget"
closure plan
closure verify --trusted
closure explain system.EXAMPLE-001
```

The second Verify intentionally returns exit 1: used allocation is 1.2 against a limit of 1. Restore `closure set system.allocation 0.5`, then Verify again. The original intact evidence can be reused. `--force` reruns all analyses in the chosen context. Saved reports remain available through `closure history`.

## Inspect in the viewer

```sh
closure serve --trusted
```

Open the printed localhost address. Select **Variables**, edit the allocation, save, then press **Verify**. A saved verification snapshot opens with the result. Return to the current project before editing again. **Requirements** explains the margin and causal path; **Evidence** reopens earlier snapshots. Stop the server with Ctrl+C.

## Wrap your own analysis

Replace `analysis/evaluate.py` with a wrapper around your existing calculation. Read declared inputs from the JSON request, write named typed outputs to the response, and keep logs on stderr. Name the sources/tools that influence the result. Replace the starter requirement and review the changed obligation baseline. The [runner guide](ENGINE_GUIDE.md), [JavaScript example](../conformance/README.md) and [CLI guide](CLI_GUIDE.md) cover the next steps.

The service example in the source archive demonstrates independent capacity and energy branches without additional dependencies. The mission, mechanical and external-tool examples require their documented optional tools. They are examples of evidence plumbing, not qualified designs.
