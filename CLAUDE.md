# CLAUDE.md

Behavioral guidelines for working in this repository. Keep them strict, practical, and minimal.

## 1. Before Coding

- Do not assume unclear requirements.
- State assumptions when they matter.
- If multiple interpretations are plausible, surface them instead of picking silently.
- If the simpler solution is sufficient, use it.
- If something important is unclear or risky, stop and ask.

For multi-step work, define a short verification-driven plan:

```text
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```

## 2. During Changes

- Make the smallest change that fully solves the task.
- Do not add features, abstractions, or configurability that were not requested.
- Match the local style of the file you are editing.
- Do not refactor adjacent code unless the task requires it.
- Remove only the unused code created by your own change.
- If you notice unrelated problems, mention them instead of fixing them opportunistically.

Every changed line should trace directly to the request.

## 3. Documentation Workflow

### Start here

Before any non-trivial task:

1. Read [`README.md`](README.md) and use its Documentation table to find the relevant doc.
2. Read [`docs/code-map.md`](docs/code-map.md) before grepping.
3. Read the relevant `docs/*.md` file for the subsystem you are changing.

### Create a new doc only when needed

Create `docs/<topic>.md` only for:

- a new subsystem spanning 3 or more files
- a non-obvious data flow
- an area the user explicitly asked to document

Do not create docs for:

- small bug fixes
- UI tweaks
- isolated settings changes

### Update docs when behavior or structure changes

Update the relevant doc whenever you change documented architecture or behavior, including:

- endpoints
- DB schema
- provider/model flow
- localStorage keys
- major UI flows

Whenever you add, delete, rename, or move a source file, update [`docs/code-map.md`](docs/code-map.md) in the same change.

When updating docs, also patch the exact navigation gaps that slowed work earlier in the session. Keep that addition small and factual.

If docs and code disagree:

- trust code for current behavior
- update docs in the same change
- mention the mismatch in the final note

### Doc format

- Start with a one-paragraph overview.
- Link to concrete files with relative paths.
- Use tables for schema, config, or file maps.
- Use ASCII flow diagrams for request/data flows when helpful.
- Document what exists now, not what was once planned.

### Where information belongs

| Path | Role |
|------|------|
| `docs/` | Feature and subsystem documentation |
| `README.md` | Run instructions and docs index |
| `CLAUDE.md` | Agent behavior and workflow rules |

After creating or updating a doc in `docs/`, update its entry in the `README.md` Documentation table.

## 4. Testing

After every code change, run tests. This is mandatory.

```powershell
npm test
npm run test:backend
npm run test:compute
npm run test:frontend
```

Rules:

- After refactoring, run the full `npm test` from repo root.
- For a small isolated change, the relevant targeted suite is acceptable.
- When in doubt, run everything.
- If you intentionally change documented behavior, update the code, the docs, and the tests together.
- Add tests for non-trivial logic and calculations that are documented or easy to regress.
- Do not add tests for trivial code.
- A task is not complete while required tests are failing.

Test files live in:

- `backend/tests/`
- `compute/tests/`
- `frontend/src/**/*.test.ts`

See [`docs/testing.md`](docs/testing.md) for suite details.

## 5. Project-Specific Guidance

Current architecture lives in `docs/`. Treat it as the source of truth for understanding the system.

Use [`docs/excluded-from-analysis/`](docs/excluded-from-analysis/README.md) only when the user explicitly asks for that material. It is out of scope for routine coding, exploration, and doc updates.

In particular, do not read or update `docs/excluded-from-analysis/` during normal work unless the request is specifically about those files or topics.
