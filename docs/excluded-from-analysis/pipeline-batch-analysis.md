# Батч-анализ: `batch_analysis_gemini` (+ `reclassify_unclassified` / `reclassify_all`)

Текстовый (без картинок) батч-анализ через Gemini Batch API. Всегда
предполагает, что `ocr_text` уже есть — картинка документа тут никогда не
участвует, значит **тип файла (.docx/pdf/скан) роли не играет**, важен только
факт наличия текста.

Реализация: [`batch_analysis.py`](../../backend/app/services/batch_analysis.py).
`batch_analysis_gemini` не создаётся напрямую из UI задач — это движок под
капотом двух других задач (`doc_scope` разный).

## Кто есть кто

```
run_batch_analysis_gemini(doc_scope=...)
        │
        ├─ doc_scope="needs_analysis" (по умолчанию, прямой вызов API)
        │     ocr_text не пусто И manually_classified≠true И
        │     (analysis_status≠"done" ИЛИ type IN unclassified/other/NULL)
        │
        ├─ doc_scope="unclassified"  ──► задача reclassify_unclassified
        │     ocr_status="done" И manually_classified≠true И
        │     type IN (unclassified, other, NULL) И ocr_text не пусто
        │
        ├─ doc_scope="pending"       ──► задача reclassify_all
        │     ocr_status="done" И analysis_status≠"done" И ocr_text не пусто
        │
        └─ doc_ids=[...]  (явный список id, например из fix_quality) ──►
              переопределяет doc_scope полностью, фильтры не применяются
```

## Обработка одного документа

```
для каждого документа в scope
        │
   snippet = ocr_text[:4000] (или vision_description, если ocr_text пуст)
        │
   snippet пуст? ──да──► пропуск, лог "no text to analyze"
        │нет
        ▼
   JSONL-строка: {"key": doc.id, ANALYSIS_SYSTEM + snippet, max_output_tokens=1024}
        │
        ▼  (все строки в один файл)
   upload → batchGenerateContent → поллинг (poll_interval) до SUCCEEDED
        │
        ▼
   на каждую строку результата:
      error? ──да──► failed++, лог с текстом ошибки
      иначе ──► parse_llm_json(text) → summary/title/type/tags/lang/
                 org/amount/person/date, analysis_status="done",
                 classification_source="auto"
                 сразу же _run_embedding(doc) — пере-embed, чтобы
                 semantic search/`/ask` увидели новый summary
```

## Отличие от `batch_ocr_gemini`

| | `batch_ocr_gemini` | `batch_analysis_gemini` |
|---|---|---|
| Картинка документа | иногда (если ocr_text ещё пуст) | никогда |
| `ocr_status` scope | `pending` (текста ещё нет) | `done` (текст уже есть) |
| Что пишет | `ocr_text` и/или анализ | только анализ |
| Реэмбеддинг после записи | нет | да, сразу после каждого документа |

## Три способа реклассификации — не путать

Все три меняют `document_type`, но по-разному и с разной ценой:

| Способ | Что делает | Стоимость | Затрагивает |
|---|---|---|---|
| `reclassify_pending_batch` ("Re-classify All", НЕ batch API) | 1 дешёвый синхронный LLM-вызов на документ — **только тип**, по уже существующему summary | 1 вызов/док, дёшево | документы с summary; старый тип сохраняется в tags |
| `reclassify_unclassified` (`doc_scope="unclassified"`, через batch) | полный анализ (summary+tags+type+...) для НЕклассифицированных | batch-цена, но полный набор полей | только `unclassified`/`other`/`NULL`, не тронутые вручную |
| `recluster` | локальная кластеризация всех summary + 1 LLM-вызов **на кластер**, а не на документ | самый дешёвый по числу LLM-вызовов | ВСЕ документы с summary, независимо от текущего типа |

См. [pipeline-recluster.md](pipeline-recluster.md) для последнего.
