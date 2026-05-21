# Testing Strategy — Content Factory

## Rule
Every story ships with tests. CI must be green before a story is marked complete.

## Test layers

### Unit tests (required for every story)
- Location: `tests/test_*.py`
- Scope: single function or class
- External APIs: always mocked
- Run with: `pytest -m "not integration"`
- Must pass in CI

### Integration tests (optional, run locally only)
- Location: `tests/integration/test_*.py`
- Scope: real API calls (Drive, Claude, Pexels, Replicate)
- Excluded from CI via pytest marker
- Use sparingly — smoke tests cover the same ground manually

## Mocking conventions

Use `unittest.mock.patch` or `pytest-mock` to mock:
- `src.drive.DriveClient` — mock folder creation, file upload/download
- `anthropic.Anthropic.messages.create` — mock Claude API responses
- `requests.get` / `requests.post` — mock Pexels, Freesound
- `replicate.run` — mock Replicate predictions

Always mock at the import boundary (patch the name where it's used, not where it's defined).

## What to test per story

| Story type | Required tests |
|------------|---------------|
| API endpoint | Happy path, missing/invalid input (422), upstream error (500) |
| Service module | Happy path, API error handling, fallback logic |
| Parsing/validation | Valid input, invalid/malformed input, edge cases |

## Minimum test cases per function
1. Happy path — expected input, expected output
2. One failure case — API down, invalid response, missing field

## CI configuration
See `.github/workflows/ci.yml`. Tests run on every push to any branch.
```
pytest tests/ -m "not integration" --tb=short
```

## Coverage
No hard coverage threshold for POC. Aim for all critical path functions covered.
