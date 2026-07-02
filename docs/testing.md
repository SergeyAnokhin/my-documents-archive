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

Tests that exercise a paid external AI/API call (OpenAI, Gemini, Mistral, DeepSeek,
OpenRouter, HuggingFace datasets, the external OCR worker) always mock the
SDK/HTTP boundary (`openai.AsyncOpenAI`, `google.genai.Client`, `httpx.AsyncClient`)
— no test ever makes a real, billable request. These are marked **(mocked)** below
and pin both request construction (are the right params/payloads built?) and
response parsing (is the provider's response correctly turned into internal data?).

| Suite | File | Pins |
|-------|------|------|
| backend | [test_storage.py](../backend/tests/test_storage.py) | MIME fallback by extension, supported-extension check, upload name-collision (`doc.png` → `doc_1.png`) |
| backend | [test_search.py](../backend/tests/test_search.py) | `services/search_query.py`: `_highlight` snippet/ellipsis, hybrid merge order (both → semantic-only → fulltext-only) + dedupe, `_parse_query` quoted-phrase split, `_transliterate_cyr_to_lat` + `_expand_fulltext_query` cross-script name variants |
| backend | [test_qa.py](../backend/tests/test_qa.py) | `/ask` QA pipeline (`services/qa.py`): context assembly (numbered `[i]` blocks, metadata fields, per-depth OCR truncation), prompt construction (response language, citation instruction), `_DEPTH_CFG` token budgets. **(mocked)** `run_text` boundary: provider priority by `sort_order`, empty-query/no-provider guards never call the LLM, answer/tokens/cost passthrough, LLM-failure → error text + zero cost, `record_usage(usage_type="qa")` ledger row |
| backend | [test_ai_analysis.py](../backend/tests/test_ai_analysis.py) | `_parse_result`: code-fence stripping, type coercion, empty/absent → None, documented defaults. **(mocked)** `_call_openai_compatible`/`_call_gemini` request construction: per-provider model/base_url defaults, json-mode/response_format branching, system+user message shape |
| backend | [test_ai_vision.py](../backend/tests/test_ai_vision.py) | Mistral OCR page-join/pricing, `VISION_FULL_PROMPT` taxonomy sharing, vision-JSON parsing. **(mocked)** `_call_openai_compat`/`_call_gemini`/`_call_mistral_ocr` request construction: image payloads, extra_params (temperature/max_tokens), response_schema vs json_mode, Mistral OCR endpoint/payload |
| backend | [test_provider_models.py](../backend/tests/test_provider_models.py) | **(mocked)** model-list fetch + reshape for openai/gemini/mistral/deepseek/openrouter: known-model pricing lookup, Gemini pricing inference for unknown models, deprecated/versioned-snapshot filtering, OpenRouter negative-price clamping, `fetch_models` dispatch + never-raises contract |
| backend | [test_arena_ratings.py](../backend/tests/test_arena_ratings.py) | `_score_to_stars` thresholds, `_pick_col` schema fallback. **(mocked)** HuggingFace dataset fetch/aggregation (lmarena + lmsys), `refresh_ratings` merge-over-hardcoded and fallback-on-error |
| backend | [test_batch_analysis.py](../backend/tests/test_batch_analysis.py) | `doc_scope` document-selection filters (`needs_analysis`/`unclassified`/`pending`/explicit `doc_ids`). **(mocked)** Gemini Batch API JSONL request shape, upload/create/poll/download flow, result-line parsing (success/error/bad-date), resume-job path |
| backend | [test_batch_ocr.py](../backend/tests/test_batch_ocr.py) | `_needs_vision` hybrid routing (vision vs reuse-existing-text). **(mocked)** Mistral + Gemini batch OCR: JSONL request shapes, file-upload/batch-create payloads, status-polling interpretation, output-file fallback chain, result-line parsing (vision vs text-only, success/error), resume-job path |
| backend | [test_ocr.py](../backend/tests/test_ocr.py) | `_mime_for` extension mapping, local-vs-external engine fallback chain (`extract_text`). **(mocked)** `_external_ocr` request construction (worker URL/params/multipart file) and response parsing (text/engine defaults) |
| backend | [test_recluster.py](../backend/tests/test_recluster.py) | `_strip_for_clustering` (date/name/tag stripping + short-fallback), `_k_range` bounds, `_apply_new_type` tag preservation, `_save_cluster_data` upsert/built-in-skip. **(mocked)** `_name_cluster` prompt construction (AVAILABLE/EXCLUDED icons) and conflict-aware retry loop |
| backend | [test_indexer.py](../backend/tests/test_indexer.py) | `_apply_analysis_result` writes all metadata columns, invalid-date handling, `_is_unclassified` predicate |
| backend | [test_lab.py](../backend/tests/test_lab.py) | Lab judge-output parsing (plain/fenced JSON, garbage), prompt construction (verbatim+JSON request, language, conditional "corrected" field) |
| backend | [test_pricing.py](../backend/tests/test_pricing.py) | `estimate_cost`: known-model per-token table, unknown-model → 0, linear scaling |
| backend | [test_tasks_recovery.py](../backend/tests/test_tasks_recovery.py) | Startup recovery of orphaned "running" tasks: batch tasks with a remote job auto-resume, everything else resets to "stopped" |
| backend | [test_type_icon_suggestion.py](../backend/tests/test_type_icon_suggestion.py) | Icon-suggestion conflict/retry loop, `get_pending_custom_types` built-in/assigned exclusion, `custom_type_icons` persistence round-trip. **(mocked)** LLM call via `run_text` |
| backend | [test_db_backup.py](../backend/tests/test_db_backup.py) | Backup list + restore round-trip, pre-restore snapshot, path-traversal/prefix guard |
| backend | [test_docx_extract.py](../backend/tests/test_docx_extract.py) | Native `.docx` extraction: paragraph joining (`"\n\n"` per block, blanks dropped), table rows as `" \| "`-joined cells, document-order concatenation |
| compute | [test_ocr_worker.py](../compute/tests/test_ocr_worker.py) | `/health` shape, `/ocr` returns 400 on an unreadable file, `_to_images` junk→`[]` / valid PNG→1 RGB image |
| frontend | [client.test.ts](../frontend/src/api/client.test.ts) | API client: 204 → `undefined`, error response throws server `detail` |
| frontend | [i18n.test.ts](../frontend/src/i18n/i18n.test.ts) | EN, RU **and** FR expose an identical key set |
| frontend | [aiUtils.test.ts](../frontend/src/components/admin/tabs/ai/aiUtils.test.ts) | `fmtTokens` K/M, `blendedPrice` 75/25 blend + sub-cent, `lookupModelRating` 5-tier fallback (exact → prefix → date → preview → Gemini family) |
| frontend | [labUtils.test.ts](../frontend/src/pages/lab/labUtils.test.ts) | `formatMs` / `formatFileSize` unit boundaries (ms/s/min, B/KB/MB) |
| frontend | [imgSrc.test.ts](../frontend/src/components/documents/imgSrc.test.ts) | `resolveImgSrc`: undefined vs rawSrc passthrough, data-URL construction from a preview b64 |
| frontend | [typeIcons.test.ts](../frontend/src/components/documents/typeIcons.test.ts) | `iconForType`: built-in taxonomy lookup, keyword fallback, custom-icon override via `setCustomTypeIcons`, `ICON_NAME_MAP` completeness |

## Conventions

- Tests pin **documented behavior**, not implementation detail. Each test file names
  the doc that defines the rule it protects (see the docstring/header).
- When you intentionally change a documented rule, update the doc, the test, and the
  code together (per `CLAUDE.md` §6).
- Add a test only for non-trivial logic — calculations, ordering rules, fallbacks,
  invariants. Do not test trivial getters or UI markup.
- Backend tests must not touch the real library: monkeypatch `settings.library_path`
  to a `tmp_path` (see `test_storage.py`).
