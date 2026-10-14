# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Report them privately through
[GitHub security advisories](https://github.com/botifyex/egress-proxy/security/advisories/new)
with a description, the affected version and, if possible, steps to reproduce.

You will get an answer within a week. Once a fix is released, the advisory is published with
credit to the reporter unless you prefer otherwise.

## Supported versions

Only the latest release receives security fixes.

## Scope

Of particular interest are ways to:

- use the server without a valid key;
- reach loopback, private or link-local addresses while `PROXY__ALLOW_LOCAL` is off;
- make the target see the client's address or other identifying headers;
- leak upstream proxy credentials.
