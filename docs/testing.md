# Testing — DocIntel

Three independent suites, one orchestrator. `npm test` from the repo root runs all
three in order (backend → compute → frontend) and stops on the first failure.

## Commands

| Command | Runs |
|---------|------|
| `npm test` | All three suites (from repo root) |
| `npm run test:backend` | `cd backend && python -m pytest` |
| `npm run test:compute` | `cd compute && python -m pytest` |
| `npm run test:frontend` | `cd frontend && npm test` (vitest) |

First-time setup: `cd frontend && npm install` (pulls vitest). Backend/compute use
the same Python env that runs the services — pytest must be importable there.

Output is intentionally terse: pytest runs with `-q --tb=short` (baked into each
`pytest.ini`), vitest with `--reporter=dot`. On success only totals print.

## What is covered

| Suite | File | Pins |
|-------|------|------|
| backend | [test_storage.py](../backend/tests/test_storage.py) | MIME fallback by extension, supported-extension check, upload name-collision (`doc.png` → `doc_1.png`) |
| backend | [test_search.py](../backend/tests/test_search.py) | `_highlight` snippet/ellipsis, hybrid merge order (both → semantic-only → fulltext-only) |
| compute | [test_ocr_worker.py](../compute/tests/test_ocr_worker.py) | `/health` shape, `/ocr` returns 400 on an unreadable file |
| frontend | [client.test.ts](../frontend/src/api/client.test.ts) | API client: 204 → `undefined`, error response throws server `detail` |
| frontend | [i18n.test.ts](../frontend/src/i18n/i18n.test.ts) | EN and RU expose an identical key set |

## Conventions

- Tests pin **documented behavior**, not implementation detail. Each test file names
  the doc that defines the rule it protects (see the docstring/header).
- When you intentionally change a documented rule, update the doc, the test, and the
  code together (per `CLAUDE.md` §6).
- Add a test only for non-trivial logic — calculations, ordering rules, fallbacks,
  invariants. Do not test trivial getters or UI markup.
- Backend tests must not touch the real library: monkeypatch `settings.library_path`
  to a `tmp_path` (see `test_storage.py`).
