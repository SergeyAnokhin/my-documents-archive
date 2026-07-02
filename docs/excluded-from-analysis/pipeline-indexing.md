# Обычная индексация одного документа

Запускается: после upload, после `sync_library`, и задачей `index_unindexed`.
Реализация: [`backend/app/services/indexer.py`](../../backend/app/services/indexer.py)
`index_document()`. См. также [architecture.md](../architecture.md).

Режим (`AppSettings.auto_process_mode`) заранее решает, докуда доехать:

```
force_full=True (кнопка "Reindex")  ─────────────────────► всегда режим "full"
иначе AppSettings.auto_process_mode:
  full      → все шаги
  ocr_only  → только OCR/native-extract + thumbnail, Vision/Analysis пропуск
  manual    → только thumbnail; ocr_status остаётся pending
              (документ ждёт batch-OCR задачу)
```

## Общая схема, ветвление по типу файла

```
                         index_document(doc)
                                │
                    ┌───────────┴────────────┐
                 .docx?                    нет (pdf/image)
                    │                          │
                    │                    mode!=manual? ─нет─► нет thumbnail? уже готов? см. ниже
                    │                          │да
                    │                    Thumbnail (Pillow/pdf2image)
                    │                          │
        (thumbnail НЕ генерится:               │
         у docx нет рендера страницы)           │
                    │                          │
              mode==manual? ──да──► STOP (ocr_status=pending, thumbnail для не-docx уже сделан)
                    │нет                        │нет (mode!=manual)
                    ▼                          ▼
     native text extract              .pdf? ──да──► pdf_extract.extract_pdf_text()
     (docx_extract, python-docx)                      │ (только текстовый слой, без OCR)
     ocr_model="native"                     текст длиной >= MIN_TEXT_LENGTH?
     vision_status="skipped"                    да ──► ocr_status=done, ocr_model="native"(pdf)
     (рендера страницы нет —                    нет/None ──► fallback: Tesseract / worker OCR,
      Vision никогда не запустится                          ВСЕ страницы, ocr_model="tesseract"/"easyocr"
      для docx)                              │
                                       не .pdf (картинка) ──► сразу Tesseract/worker OCR
                    │                          │
                    └────────────┬─────────────┘
                                 mode=="full"? ──нет(ocr_only)──► STOP здесь (перейти к Embedding)
                                  │да
                     .docx? ──да──► Vision пропускается (нет картинки)
                        │нет
                        ▼
                 enable_ai_vision==true? ──нет──► vision_status="skipped"
                        │да
                картинка 1-й страницы → describe_document()
                        │
              провайдер vision-capable
              (OpenAI/Gemini/OpenRouter)? ──да──► VISION_FULL_PROMPT
                        │                          → JSON {текст + ВСЕ поля анализа}
                        │                          │
                        │                    len(ocr_text) < 200 симв.? (VISION_ANALYSIS_OVERRIDE_MAX_OCR_LEN)
                        │                          да ──► применить как Analysis,
                        │                                  analysis_status="done", Step4 SKIP
                        │                          нет ──► только vision_description сохранён,
                        │                                  Step4 (Analysis) выполнится по полному тексту
                        │нет (Mistral)
                        └──► Mistral OCR: только сырая транскрипция
                              (plain text, без JSON-полей) → Step4 ВСЕГДА выполняется

                 Step4 — AI Analysis (если не пропущен выше):
                     analysis_status=="done"? ──да──► SKIP (уже готово)
                     ocr_text и vision_description оба пусты? ──да──► analysis_status="skipped"
                     иначе ──► LLM: summary, title, type, tags, language, org, amount

                 Step5 — Embedding (всегда, вне зависимости от mode):
                     summary или ocr_text[:1500] непустые? ──да──► ChromaDB vector
                     иначе ──► пропуск молча
```

## Итог по типам документов (mode=full)

| Тип | OCR/extract | Thumbnail | Vision | Analysis |
|---|---|---|---|---|
| `.docx` | нативный (python-docx), `ocr_model="native"` | нет (пропуск) | нет (пропуск, `vision_status="skipped"`) | всегда Step4 (нет короткого vision-JSON, который мог бы его заменить) |
| PDF с текстовым слоем | `pdf_extract` (без OCR) | да | да, если включён | пропускается только если vision дал полный JSON и текст короткий (<200 симв.) — на многостраничном PDF с текстовым слоем это редкость |
| PDF-скан / картинка | Tesseract/worker OCR, все страницы | да | да, если включён | то же правило, что выше |

**Важный нюанс:** Vision видит только **первую страницу** (`ai_vision.load_first_page`,
`first_page=1, last_page=1`). Если она — обложка/титул многостраничного PDF, а Vision
успевает "закоротить" Step4 (короткий предыдущий текст < 200 симв.), summary/tags
могут отражать только обложку. Обычно это не проблема, потому что pdf_extract/OCR
к этому моменту уже дали полный текст документа длиннее порога.
