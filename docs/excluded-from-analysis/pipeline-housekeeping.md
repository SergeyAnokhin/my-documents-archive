# Мелкие задачи: sync, embed_missing, fix_quality, cleanup_missing, compress_images

Реализация: [`task_runners.py`](../../backend/app/services/task_runners.py)
(кроме `compress_images` — [`image_compress.py`](../../backend/app/services/image_compress.py)).

## `sync_library`

```
scan_library_for_new_files(known=все filepath из БД, is_deleted=False)
        │
для каждого нового файла:
   hash уже есть в БД (дубликат по содержимому под другим путём)? ──да──► пропуск
   иначе ──► создать Document(source="sync"), thumbnail,
              index_document() (обычный пайплайн, см. pipeline-indexing.md)
```
Отдельно (не в этой функции, а в `/api/admin/sync`): перед сканом —
`check_library_accessible()` (503, если диск/NAS не смонтирован — защита от
случайного массового удаления), затем hard-delete документов с исчезнувшим
файлом.

## `embed_missing`

```
embeddable = все документы (не удалены) у которых summary ИЛИ ocr_text не пусты
        │
   config.force==true? ──да──► пере-embed ВСЕ embeddable (игнорируя существующие вектора)
                        ──нет──► только те, кого нет в embedded_ids() (ChromaDB)
        │
для каждого ──► indexer._run_embedding(doc)  (то же, что Step5 обычного пайплайна)
```
Тип файла не важен — решение только по наличию текста и наличию вектора.

## `fix_quality` — маршрутизация по конкретному пробелу

```
quality_filter = "no_ocr" | "no_embedding" | "no_analysis" |
                  "no_summary" | "no_tags" | "no_category"
        │
   "no_ocr"       ──► docs: ocr_status≠"done" ИЛИ ocr_text пуст
                        операция: index_document() по одному, синхронно
                        (обычный пайплайн: docx→native, pdf→pdf_extract/OCR, image→OCR)
        │
   "no_embedding" ──► docs: id НЕ в embedded_ids()
                        операция: embed_document_by_id() по одному
        │
   "no_analysis"  ──► docs: analysis_status≠"done"
   "no_summary"   ──► docs: summary пуст                    ┐
   "no_tags"      ──► docs: tags == [] или пуст              ├─ operation="batch_analysis"
   "no_category"  ──► docs: type IN (NULL, unclassified,     │
                              other)                          ┘
                        операция: ОДИН вызов
                        run_batch_analysis_gemini(doc_ids=[явный список]) —
                        см. pipeline-batch-analysis.md, doc_scope игнорируется,
                        т.к. передан явный doc_ids
```
Ключевое: 4 из 6 типов пробелов (`no_analysis`/`no_summary`/`no_tags`/
`no_category`) уходят в тот же батч-движок, что `reclassify_*`, а не
обрабатываются документ-за-документом синхронно — так дешевле.

## `cleanup_missing`

```
для каждого документа (не удалён):
   Path(doc.filepath).exists()? ──нет──► is_deleted=True (soft-delete)
                                 ──да──► пропуск
```
Файлы не трогает, ничего не скачивает/не анализирует — чистая сверка БД↔диск.

## `compress_images`

```
кандидаты: расширение in {.jpg,.jpeg,.png,.tiff,.tif,.webp}
        │
для каждого:
   файл не существует на диске? ──да──► skipped
   max(width,height) <= max_long_side (порог, по умолчанию 1024px)? ──да──► skipped
   иначе ──► resize (PIL LANCZOS) → пересохранить на том же пути
              (JPEG/WEBP quality=85), пересчитать file_hash/file_size в БД
```
PDF/`.docx` не участвуют — только растровые изображения. OCR-текст/анализ не
трогает — только байты файла на диске и `file_hash`/`file_size` в БД (значит
после этой задачи `sync`/дедупликация по хэшу увидят "новый" хэш того же
документа).
