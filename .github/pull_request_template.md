## Summary

<!-- What changed, and why does it matter? -->

## Verification

<!-- List commands, tests, and manual checks. -->

- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `mypy src`
- [ ] `pytest`

## Security and privacy

- [ ] Fixtures, logs, screenshots, and examples contain no real secrets or private payloads.
- [ ] I considered redaction, SSRF, prompt injection, and generated-code risks where relevant.
- [ ] Outbound HTTP and AI provider calls are mocked in tests.
- [ ] Documentation and `.env.example` reflect any public configuration changes.

## UI evidence

<!-- For visible changes, add redacted before/after screenshots. Otherwise write “Not applicable.” -->
