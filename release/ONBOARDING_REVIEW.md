# Independent first-session review

For `0.1.0a1`, independent onboarding is explicitly deferred to public-preview feedback. This is a prepared acceptance exercise, **not an observed external user result**. Ask an engineer who did not build Closure to use only the public candidate archive and quickstart. Do not preconfigure their project.

Record their OS/Python, candidate hash, start/end time, documentation used and every point where they need assistance. The exercise is complete when they install the wheel, wrap one small existing analysis, declare its inputs/outputs and requirement, review its baseline, produce a passing Verify, change an input to cause a real failure, explain its causal path and reopen the original saved result. Have them try both the CLI and viewer and inspect the authored YAML for readability.

The first-session success criterion is independent completion within one working session, with a meaningful regression caught and explained. Do not count a canned example alone as proof of this North Star. Capture confusing vocabulary, unnecessary fields and missing help examples as release feedback.

Record the participant's permission before retaining their project or quotations. Add the actual review result to the local release review and change the onboarding status to `complete` only after evidence exists. No external contact is sent automatically by the release tooling.
