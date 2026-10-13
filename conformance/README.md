# Closure 0.1 preview conformance

Run `npm --prefix frontend ci` and `npm --prefix frontend test` for independent JavaScript/AJV schema validation and SHA256 vector checks. Run `python -m pytest tests/test_preview.py tests/test_protocol.py` for Python semantic checks and the real Node runner exchange. Node must be on PATH (or set `CLOSURE_TEST_NODE`); release CI requires the cross-language test to run.

`cases.json` has positive/negative source and runner structural cases. `canonical.json` contains raw JSON input, exact canonical UTF-8 text and its SHA256. The Python test checks canonicalization from input; the JavaScript test verifies encoding/digest of the canonical text and validates schemas independently. **The latter does not implement Python numeric canonicalization or claim complete evidence-reader conformance.** Do not use ordinary JavaScript JSON round trips to recompute 0.1 evidence hashes.

`javascript-project/` is an executable, standard-library-only runner example. Its authored `80 W + 100 W <= 200 W` budget passes after baseline review. Set `power.load` to `120 W`: the previous result becomes stale, Verify reruns the JavaScript analysis, total demand becomes `220 W` and the requirement fails by `20 W`. Restore `80 W` to recover. This is a synthetic protocol fixture, not a qualified electrical design.

```sh
closure check -p conformance/javascript-project
closure approve-baseline -p conformance/javascript-project --reviewer "Your name" --reason "Reviewed illustrative budget"
closure verify -p conformance/javascript-project --trusted
closure set power.load 120 -p conformance/javascript-project
closure verify -p conformance/javascript-project --trusted
```

The second Verify intentionally returns exit 1. The broader engine suite covers semantic conditions that JSON Schema alone cannot establish: exports, cycles, units, output names/invocation identity, solver convergence, protected limits, alternatives, review policy, stale evidence and corruption. The suite is portable, but passing these preview cases is not a universal certification or proof of physical correctness.
