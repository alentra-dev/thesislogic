# Contributing to ThesisLogic

Contributions welcome — especially jurisdiction packs, corpus importers, and provider backends.

## Ground rules

1. **The proof gate is inviolable.** PRs that weaken cite-or-decline behavior (letting unverified
   citations through, making downgrades silent, adding a bypass flag) will not be merged.
2. **Deterministic first.** Document workflows must keep a fully deterministic path; generative
   enhancements are additive and gated.
3. **No telemetry.** ThesisLogic makes network calls only to the model endpoints the deployer
   configured.
4. **Jurisdiction knowledge belongs in packs, not code.** If your change hardcodes a state name,
   reporter format, or court, it probably belongs in `pack.json`.

## Dev setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## Good first contributions

- Pack importers: scripts that convert CourtListener bulk exports, state revisor XML, or
  Fastcase-style dumps into `authorities.ndjson`.
- Curated span sets for high-citation authorities.
- Provider backends behind the existing protocols (keep them dependency-light and optional).
- Translations of the workspace UI.

## Sharing jurisdiction packs

Packs containing only public-domain primary law are ideal community contributions. Publish them
in their own repositories (they can be large) and open a PR adding a link to the pack registry in
the README. Never include client material or licensed database content in a public pack.
