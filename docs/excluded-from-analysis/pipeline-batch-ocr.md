# Батч-OCR: `batch_ocr_mistral` и `batch_ocr_gemini`

Асинхронные задачи через batch API провайдера (~50% дешевле обычного вызова).
Реализация: [`batch_ocr.py`](../../backend/app/services/batch_ocr.py) (общие
хелперы) + [`batch_ocr_mistral.py`](../../backend/app/services/batch_ocr_mistral.py) +
[`batch_ocr_gemini.py`](../../backend/app/services/batch_ocr_gemini.py). Полное
описание протокола — [batch-ocr.md](../batch-ocr.md) (это уже обычная,
не исключённая документация — здесь только диаграмма решений по документу).

Общий scope отбора: `ocr_status == "pending"`, `is_deleted == False`, до `limit`.

## `batch_ocr_mistral` — решение по документу

```
для каждого документа из scope (limit шт.)
        │
     .docx? ──да──► docx_extract.extract_docx_text() (бесплатно, локально)
        │             ocr_status="done", ocr_model="native", vision_status="skipped"
        │             ИСКЛЮЧЁН из JSONL — в Mistral /v1/ocr не отправляется вообще
        │             считается в result_summary["native"] (и в "processed")
        │
        │             extract упал (битый/зашифрован файл)?
        │             ──да──► ocr_status="error", запись в failed, из батча исключён
        │
        нет (pdf/картинка)
        ▼
  картинка 1-й страницы (load_first_page) → строка JSONL:
  {"custom_id": doc.id, "document": {"image_url": "data:...;base64,..."}}
        │
        ▼
  ОДИН batch job на все такие документы → Mistral /v1/batch/jobs (endpoint /v1/ocr)
        │
        ▼
  поллинг (poll_interval) → SUCCESS → скачать результаты → parse_mistral_ocr()
        │
        ▼
  ocr_text записан, ocr_status="done", cost_usd посчитан (per-page)
```

Если **все** документы в scope оказались `.docx` — задача завершается `"done"`
без единого обращения к Mistral API (нечего отправлять).

## `batch_ocr_gemini` — решение по документу (гибрид vision/text)

Gemini делает не только OCR, но и анализ в одном вызове — поэтому здесь
решение per-документ сложнее: картинка нужна не всегда.

```
для каждого документа из scope
        │
     .docx? ──да──► docx_extract native extract (как выше)
        │             ocr_text теперь непустой ──► _needs_vision(doc) становится False
        │             попадает в ветку "text-only" ниже (анализ всё равно выполнится)
        │
        нет
        ▼
   _needs_vision(doc):
     ocr_text уже существует (ЛЮБОЙ engine, включая локальный
     tesseract/easyocr — переиспользуется как есть)?
        │
       да ──► TEXT-ONLY: существующий ocr_text (первые 4000 симв.) + ANALYSIS_SYSTEM
               → строка JSONL без картинки → только поля анализа,
               ocr_text/ocr_model НЕ трогаются
               📝 в логах задачи
        │
       нет ──► VISION: картинка 1-й страницы + VISION_FULL_PROMPT
               → строка JSONL с inline_data (base64)
               → транскрипция + ВСЕ поля анализа одним вызовом
               🖼️ в логах задачи
        │
        ▼
  один JSONL (обе ветки внутри одного файла — Gemini batch lines независимы)
        │
        ▼
  batchGenerateContent → поллинг → скачать → распарсить per-line
        │
        ▼
  ocr_text (если был запрос vision) + поля анализа записаны;
  result_summary: vision_count / text_count / processed / failed / tokens_in/out
```

## Сравнение двух задач

| | `batch_ocr_mistral` | `batch_ocr_gemini` |
|---|---|---|
| Endpoint провайдера | `/v1/ocr` (только OCR, картинка обязательна) | `:batchGenerateContent` (текст ИЛИ картинка) |
| `.docx` в scope | извлекается нативно, **не отправляется в API** | извлекается нативно, идёт в API **как текст** (анализ) |
| Экономия на уже-OCR'ных документах | нет (только чистый OCR job) | да — text-only ветка в 2 раза дешевле |
| Что пишет в документ | только `ocr_text` | `ocr_text` (если vision) **и/или** поля анализа |
| Стоимость в result_summary | `cost_usd` (per-page) | `tokens_in`/`tokens_out` (без пересчёта в $) |

## Поведение при остановке/рестарте

Обе задачи — долгие поллеры (`asyncio` корутина внутри процесса бэкенда, без
отдельного воркера). Общее для обеих:

```
Stop в UI ──► status="stopped", локальный поллинг прекращается,
              удалённый batch job на стороне провайдера ПРОДОЛЖАЕТ работать
Resume / restart backend ──► recover_running_tasks() при старте:
    есть сохранённый batch_job_id? ──да──► переподключиться к тому же job'у
                                    ──нет──► сбросить в "stopped", нужен ручной re-run
```
