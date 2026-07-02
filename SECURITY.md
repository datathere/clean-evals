# Security Policy

## Reporting a vulnerability

Report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/datathere/clean-evals/security/advisories/new).
Do not open a public issue for a security problem.

You can expect an acknowledgement within a week. Once a fix is released,
the advisory is published with credit to the reporter unless you prefer
otherwise.

## Scope

clean-evals is a local tool without authentication, and its threat model
assumes it runs on localhost — see the Disclaimers section of the README.
Reports that amount to "an attacker who can reach the port can use the
app" describe the documented design rather than a vulnerability. In scope,
for example: path traversal, code execution from crafted dataset files,
provider API keys leaking into logs or artifacts, and flaws in the Docker
configuration that expose ports beyond loopback.

## Supported versions

Only the latest release receives security fixes.
