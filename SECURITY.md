# Security Policy

ThesisLogic handles privileged client material. Treat every deployment accordingly.

## Reporting a vulnerability

Open a GitHub security advisory (preferred) or email the maintainers via the address on the
GitHub organization profile. Please do not file public issues for exploitable vulnerabilities.
We aim to acknowledge reports within 72 hours.

## Deployment hardening checklist

- bind the app to localhost and terminate TLS at a reverse proxy;
- set `THESISLOGIC_ALLOW_REGISTRATION=false` once the first admin exists;
- run as a dedicated non-root user; restrict `data/` and `packs/` permissions to it;
- back up `data/` on your document-retention schedule and encrypt backups;
- if using cloud AI, confirm your data-processing agreement covers client material and consider
  shadow mode (`THESISLOGIC_PREFER_LIVE_OUTPUT=false`) during evaluation;
- keep OCR tooling (poppler, ocrmypdf, tesseract) patched — they parse untrusted files.

## Scope notes

- Uploaded documents are untrusted input end to end: parsed by external tools with timeouts, and
  their text is labeled as data (not instructions) in any prompt.
- Sessions are bearer tokens with TTL; there is no cookie surface.
- SQL access is parameterized throughout; there is no dynamic SQL from user input.
