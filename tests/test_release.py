"""Publication requires real CI provenance, including an explicit onboarding decision."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_check', ROOT/'tools/check_preview.py')
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)


def candidate():
    metadata = json.loads((ROOT/'release/preview.json').read_text())
    record = {'implementation_version': metadata['implementation_version'], 'source_commit': 'a'*40,
              'ci': {'conclusion': 'success', 'source_commit': 'a'*40,
                     'run_url': metadata['repository_url']+'/actions/runs/123'}}
    return metadata, record


def test_deferred_onboarding_is_explicit_not_claimed_complete():
    metadata, record = candidate()
    assert metadata['onboarding']['status'] == 'deferred_to_preview'
    assert release_check.publication_errors(metadata, record) == []
    metadata['onboarding']['reason'] = ''
    assert release_check.publication_errors(metadata, record)


def test_different_commit_ci_cannot_authorize_release():
    metadata, record = candidate()
    record['ci']['source_commit'] = 'b'*40
    assert 'Successful CI required for the exact release commit' in release_check.publication_errors(metadata, record)


def test_pending_ci_or_missing_record_cannot_authorize_release():
    metadata, record = candidate()
    record['ci']['conclusion'] = 'pending'
    assert release_check.publication_errors(metadata, record)
    assert release_check.publication_errors(metadata, None)
