# Agent Instructions

Read these files before any non-trivial task, in this order:

1. [`CLAUDE.md`](CLAUDE.md)
2. [`docs/code-map.md`](docs/code-map.md)
3. [`README.md`](README.md)
4. The relevant `docs/*.md` file for the area you are changing

Repository-specific hard rules:

- Keep `AGENTS.md` short. Do not duplicate the full behavioral rules here.
- `CLAUDE.md` is the canonical source for agent behavior.
- Update [`docs/code-map.md`](docs/code-map.md) whenever files are added, removed, renamed, or moved.
- After any code change, run the relevant tests as required by [`CLAUDE.md`](CLAUDE.md).
