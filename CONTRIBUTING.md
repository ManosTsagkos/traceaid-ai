# Contributing to TraceAid AI

Thank you for helping improve TraceAid. Small, focused changes with tests are the easiest to review.

## Development setup

1. Fork and clone the repository.
2. Create a virtual environment with Python 3.11 or newer.
3. Install the editable development package:

   ```bash
   python -m pip install -e ".[dev]"
   ```

4. Copy `.env.example` to `.env`. Real provider credentials are not required for development or tests.
5. Start the app with `uvicorn traceaid.main:app --reload`.

## Working on a change

- Create a branch from `main` using a short name such as `fix/redaction-boundary` or `feat/rate-limit-rule`.
- Keep diagnosis rules deterministic and explainable. A rule should state which evidence triggered it and what action it recommends.
- Never add real credentials, customer payloads, or unredacted production traces to fixtures.
- Mock outbound HTTP and OpenAI calls. The test suite must run offline.
- Add or update tests for behavior changes, especially for parsers, security boundaries, and fallback paths.
- Update API or architecture documentation when a public contract changes.

## Quality gates

Run the same checks used by CI before opening a pull request:

```bash
ruff check .
ruff format --check .
mypy src
pytest
```

Use `pip-audit` when changing runtime dependencies. `make check` runs the core lint, type, and test checks.

## Pull requests

In the pull-request description, include:

- the problem and why it matters;
- the chosen approach and any notable trade-offs;
- tests added or changed;
- security/privacy impact;
- screenshots for visible UI changes.

Keep generated output and unrelated formatting changes out of the diff. By contributing, you agree that your contribution is licensed under the MIT License.

## Reporting security problems

Do not open a public issue for a vulnerability or a report containing secrets. Follow [SECURITY.md](SECURITY.md) instead.
