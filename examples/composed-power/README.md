# Verify an assembly power budget

Electronics and cooling each draw 52 W. Both use one shared reference profile, independently check a 60 W allocation, and supply their demand to the assembly. The root adds their demands and checks a 110 W limit. Every file in this example is synthetic. The bundled baselines document the example allocations.

From this directory, using the candidate CLI:

```sh
closure check
closure plan
closure verify --trusted
closure set system::budget.maximum 100
closure verify --trusted
closure history
closure serve --trusted --workspace .
```

The first verification passes at 104 W and executes four analyses in a fresh copy. The second exits with status 1. It reuses all four analyses. Both components still pass. The root is 4 W over budget and the new limit also needs an obligation review. Open the saved verification in the viewer to inspect **Assessment changes**, expand **Execution and reuse**, and follow **Project structure** to the failed requirement. Restore the original 110 W limit to return to the approved design.

Use `closure history --report NEW_ID --compare OLD_ID` to choose two saved assessments. Use `closure export --report ID --output NEW_FOLDER` for the portable HTML and JSON. To verify electronics alone, run `closure verify --project electronics --trusted`. That assessment schedules electronics and its reference profile. Both the assembly and the component can reuse the same verified runs. Each selected root archives the evidence for its own reports.
