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

The frontend suite runs `tsc --noEmit` before vitest so TypeScript errors are caught
locally rather than first surfacing in a Docker build.

## What is covered

| Suite | File | Pins |
|-------|------|------|
| backend | [test_storage.py](../backend/tests/test_storage.py) | MIME fallback by extension, supported-extension check, upload name-collision (`doc.png` → `doc_1.png`) |
| backend | [test_search.py](../backend/tests/test_search.py) | `_highlight` snippet/ellipsis, hybrid merge order (both → semantic-only → fulltext-only) + dedupe, `_parse_query` quoted-phrase split, `_transliterate_cyr_to_lat` + `_expand_fulltext_query` cross-script name variants |
| backend | [test_ai_analysis.py](../backend/tests/test_ai_analysis.py) | `_parse_result`: code-fence stripping, type coercion, empty/absent → None, documented defaults |
| backend | [test_db_backup.py](../backend/tests/test_db_backup.py) | Backup list + restore round-trip, pre-restore snapshot, path-traversal/prefix guard |
| compute | [test_ocr_worker.py](../compute/tests/test_ocr_worker.py) | `/health` shape, `/ocr` returns 400 on an unreadable file, `_to_images` junk→`[]` / valid PNG→1 RGB image |
| frontend | [client.test.ts](../frontend/src/api/client.test.ts) | API client: 204 → `undefined`, error response throws server `detail` |
| frontend | [i18n.test.ts](../frontend/src/i18n/i18n.test.ts) | EN, RU **and** FR expose an identical key set |
| frontend | [aiUtils.test.ts](../frontend/src/components/admin/tabs/ai/aiUtils.test.ts) | `fmtTokens` K/M, `blendedPrice` 75/25 blend + sub-cent, `lookupModelRating` 5-tier fallback (exact → prefix → date → preview → Gemini family) |
| frontend | [labUtils.test.ts](../frontend/src/pages/lab/labUtils.test.ts) | `formatMs` / `formatFileSize` unit boundaries (ms/s/min, B/KB/MB) |

## Conventions

- Tests pin **documented behavior**, not implementation detail. Each test file names
  the doc that defines the rule it protects (see the docstring/header).
- When you intentionally change a documented rule, update the doc, the test, and the
  code together (per `CLAUDE.md` §6).
- Add a test only for non-trivial logic — calculations, ordering rules, fallbacks,
  invariants. Do not test trivial getters or UI markup.
- Backend tests must not touch the real library: monkeypatch `settings.library_path`
  to a `tmp_path` (see `test_storage.py`).
