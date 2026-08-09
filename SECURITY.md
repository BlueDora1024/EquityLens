# Security policy

## Supported versions

Security fixes target the latest released version of EquityLens.

## Reporting a vulnerability

Please do not open a public issue containing credentials, tokens, private account data, or
an exploitable proof of concept. Use GitHub's private vulnerability reporting feature for
the repository. Include the affected version, reproduction steps, impact, and the smallest
safe diagnostic excerpt.

## Data handling

EquityLens stores runtime configuration locally. Provider OAuth tokens remain under the
provider SDK's documented storage, while app settings and optional AI credentials are kept
in the local application database. Diagnostic exports redact configured secrets. Release
artifacts and the public-source mirror are scanned for databases, logs, private paths,
private keys, and secret-like tokens before publication.
