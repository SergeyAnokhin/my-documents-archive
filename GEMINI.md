# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## 5. Documentation workflow

### Before starting any non-trivial task

Check `README.md` → Documentation table for relevant docs, then read the doc before touching the area. Example: changing AI analysis → read [`docs/ai-analysis.md`](docs/ai-analysis.md) first.

**To find which file owns something, open [`docs/code-map.md`](docs/code-map.md) first** — it maps every file to its responsibility. Grep only when the code-map doesn't answer.

### When to create a doc

Create a new `docs/<topic>.md` when a feature area is large enough that future work requires understanding its architecture before editing it. Good candidates:
- New subsystem with 3+ files (e.g., AI analysis, delete flow, thumbnail pipeline)
- A non-obvious data flow (e.g., how objects flow from prompt → DB → icon)
- Any area the user says "document this"

Do **not** create docs for: single-function fixes, UI tweaks, settings additions.

### When to update a doc

Update the relevant doc whenever you change the architecture of a documented area — new endpoints, DB schema changes, new display locations, new providers, changed localStorage keys. The user may also say **"обнови документацию"** — treat that as: update all docs affected by recent changes.

**Whenever you add, delete, rename, or move a source file, update [`docs/code-map.md`](docs/code-map.md) in the same change.** A stale code-map sends every future search to a dead end — this rule is not optional.

**Also fix gaps found during search.** When updating docs, look back at what was slow to locate at the start of the session (had to grep instead of reading a doc, found nothing in `ai.py` but the endpoint was in `thumbnails_api.py`, a file wasn't listed in code-map, etc.). Add exactly that missing fact to the relevant doc — even if it's unrelated to what was changed. One or two targeted additions per session, not a full rewrite.

### Doc format

- Lead with a one-paragraph overview
- Link to specific files with relative paths (`../frontend/src/...`)
- Use tables for schema, config, and file maps
- Use flow diagrams (ASCII) for request flows
- Keep it factual — what exists now, not what was planned

### Where docs live

| Path | What goes there |
|------|----------------|
| `docs/` | Feature/subsystem architecture docs |
| `README.md` | How to run + table of contents linking to `docs/` |
| `CLAUDE.md` | AI assistant behavioral guidelines (this file) |

After creating or updating a doc, add/update its entry in the `README.md` Documentation table.

---

## 6. Project description

**Current architecture is in `docs/` — that is the source of truth.** Use the
Documentation table in [`README.md`](README.md) as the index; before touching any
feature area, find the relevant doc there and read it first.

The `technical-specifications/` directory contains a high-level functional spec
written for external handoff / rebuilding from scratch. **Do not read it during
normal development work** — it is not code-level and costs tokens without
adding information beyond `docs/`. Open it only when explicitly asked to work
with the spec itself (e.g. "update the spec", "read the technical
specification"). For all code tasks, `docs/` is the source of truth.