# Coordinated preview release

The review unit is specification revision `preview.1`, source/runner 0.1, Python `0.1.0a1`, and viewer `0.1.0-alpha.1`. Licensing is Apache-2.0, copyright Keystone Intelligence LLC. The website is [Keystone Intelligence](https://www.keystoneintelligence.ai/); source is [keystoneintelligence/closure](https://github.com/keystoneintelligence/closure).

## Prepare and review

1. Run `python tools/check_preview.py`, the core tests, frontend tests, browser tests and platform package checks. Use the workflow in `.github/workflows/check.yml` for the supported matrix. CAD/external integrations are optional and have separate dependencies.
2. Build the viewer, then use `python tools/prepare_preview.py --output dist/review-N` to create a new allowlisted source tree, deterministic source ZIP and SHA256 manifest. It excludes raw conversation, local evidence, generated engineering deliverables, environments and development logs.
3. Build distributions **from that curated source tree** with `python -m build`. Validate metadata with `python -m twine check dist/*`. Exercise each wheel in a genuinely new environment using `python tools/smoke_wheel.py PATH_TO_WHEEL --isolated`. Record the resolved dependency versions.
4. Inspect the complete archive file list and license notices. Review the website pages in the existing site shell. For this early release candidate, onboarding is explicitly deferred to preview feedback; retain the exercise in `release/ONBOARDING_REVIEW.md` and record actual results when observed.
5. Keep product versions and owner approvals in `release/preview.json`. After CI succeeds, create an external `release-record.json` containing `implementation_version`, the 40-character `source_commit`, and `ci` with `conclusion: success`, the same `source_commit`, and the GitHub Actions `run_url`. Run `python tools/check_preview.py --publication --release-record PATH`. Publish this record alongside the artifacts and checksums. Keeping final provenance outside the source tree avoids a commit needing to contain its own hash. Owner sign-off does not replace CI evidence.

There is deliberately no upload, package publishing, Git push, release creation or deployment command in the preparation tools or CI. The workflow creates review artifacts only. Publication is a separate authorized step after reviewing exact bytes and checksums. Do not upload the whole local working directory.

## Release artifacts and website

Offer the versioned specification/schema/conformance source, source ZIP, Python wheel and source distribution together. The viewer is included in the wheel, with its own product description and compatibility boundary. No separate npm package is needed. Keep versioned URLs and checksums; update a “latest preview” link only after all coordinated artifacts are available.

The website should present the readable contract, reference CLI/backend and local visualization tool as three complementary entry points. Installation instructions use the actual downloaded wheel until package-index publication is separately approved. Do not imply a remote Verify service or advertise a production-certified standard.

The preview feedback questions are first-session setup, authoring verbosity, cross-language integration, practical dependency capture and requirement explanations. Known boundaries include the Python numeric digest profile, trusted local execution, unauthenticated review provenance, incomplete arbitrary-tool environment capture and no observed independent onboarding until that review is recorded.

## Rollback

Retain the preceding artifacts, source tag and static website release. Withdraw a faulty preview link rather than overwriting versioned downloads. Publish a corrected alpha version with changed contracts identified in the changelog. Existing users can reinstall the prior wheel in its own environment and inspect/export historical records. Never rewrite historical evidence to make it match a new engine.
