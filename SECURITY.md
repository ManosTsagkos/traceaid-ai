# Security policy

## Supported versions

TraceAid AI is currently pre-1.0. Security fixes are applied to the latest version on the `main` branch.

| Version | Supported |
| --- | --- |
| Latest `main` / latest release | Yes |
| Older snapshots | No |

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting feature for this repository. If private reporting is unavailable, contact the repository owner through the private contact method listed on the [GitHub profile](https://github.com/ManosTsagkos). Do not include live API keys, access tokens, cookies, or sensitive production payloads in the initial report.

Include, when possible:

- the affected endpoint or component;
- a minimal reproduction using synthetic data;
- the security impact and required preconditions;
- whether the issue has been disclosed elsewhere;
- a suggested mitigation, if known.

You can expect an acknowledgement within five business days. Disclosure timing will be coordinated after the issue is validated and a fix is available.

## Security boundaries

TraceAid accepts user-supplied URLs, headers, bodies, and failure responses. Treat every submission as untrusted.

- Live probes are disabled by default and should remain disabled on public deployments unless there is an operational need and appropriate network isolation.
- The URL validator is a defense-in-depth control, not a replacement for egress firewall rules. Production deployments should deny access to instance metadata, internal networks, and control-plane services at the network layer.
- Redaction lowers accidental exposure risk but cannot identify every possible proprietary value. Review exports before sharing them.
- Generated fixes and tests are suggestions. Review them before execution, particularly when they contain target URLs or request bodies.
- AI enrichment sends minimized, redacted evidence to the configured provider. Review that provider's data controls before enabling it.

The detailed abuse cases and mitigations are documented in [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## Deployment checklist

- Use an exact `TRACEAID_ALLOWED_ORIGINS` list; never pair wildcard origins with credentials.
- Keep `TRACEAID_ENABLE_LIVE_PROBES=false` unless replay is required.
- Terminate TLS at a trusted reverse proxy.
- Add authentication and rate limiting before any internet-facing deployment.
- Store `OPENAI_API_KEY` in a secrets manager, not an image, repository, or compose file.
- Run the container without root privileges and with the supplied capability restrictions.
- Pin and scan deployed dependencies and images.
- Avoid request-body logging and protect application logs as sensitive data.

## Out of scope

Reports about intentionally disabled live probes, self-hosted deployments that remove documented safeguards, or exposed credentials not committed by this project may be closed as configuration issues. Responsible reports that show a bypass of a documented security control remain in scope.
