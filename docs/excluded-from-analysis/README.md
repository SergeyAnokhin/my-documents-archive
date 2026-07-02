# excluded-from-analysis/

**Не читать и не обновлять эти файлы при обычной работе над проектом** (код,
баги, рефакторинг, `/update-docs`, "обнови документацию"). Всё, что лежит в
этой папке, открывается **только по прямому запросу** — когда явно попросили
показать/обновить конкретный файл или тему отсюда.

Причина: это либо огромные справочные документы (спецификации), либо личные
шпаргалки "как устроен пайплайн", которые не нужны для повседневных code-задач
и просто съедают токены/контекст, если читать их каждый раз.

## Что тут лежит

| Файл | Что это |
|------|---------|
| [First_Specification.md](First_Specification.md) | Полная продуктовая спецификация (для внешней передачи / rebuild с нуля) |
| [k3s-platform-deployment.md](k3s-platform-deployment.md) | Общий контракт платформы k3s+ArgoCD+GHCR (read-only spec) |
| [pipeline-indexing.md](pipeline-indexing.md) | Обычная индексация одного документа (upload / sync / `index_unindexed`): OCR → Thumbnail → Vision → Analysis → Embedding, ветвление по типу файла |
| [pipeline-batch-ocr.md](pipeline-batch-ocr.md) | Батч-задачи `batch_ocr_mistral` и `batch_ocr_gemini` |
| [pipeline-batch-analysis.md](pipeline-batch-analysis.md) | Батч-задача `batch_analysis_gemini` и обёртки `reclassify_unclassified` / `reclassify_all` |
| [pipeline-recluster.md](pipeline-recluster.md) | Задача `recluster` — пересборка категорий кластеризацией |
| [pipeline-housekeeping.md](pipeline-housekeeping.md) | Мелкие задачи: `sync_library`, `embed_missing`, `fix_quality`, `cleanup_missing`, `compress_images` |
| [pipeline-lab.md](pipeline-lab.md) | OCR Lab (`/lab/:id`) — ручное сравнение методов на одном документе, ничего не пишет в БД без Save |

## Матрица: тип документа × задача

Коротко, что происходит с документом в каждой задаче. Подробности — в файлах
выше.

| Задача | `.docx` | PDF с текстовым слоем | PDF-скан / картинка |
|---|---|---|---|
| `index_unindexed` (обычная индексация) | нативный текст (`docx_extract`), Vision/Thumbnail пропускаются | `pdf_extract` (без OCR) | Tesseract/worker OCR (все страницы) |
| `batch_ocr_mistral` | native extract, **в JSONL не попадает вообще** | не выбирается в scope (уже не `ocr_status=pending` после индексации) | картинка 1-й страницы → Mistral `/v1/ocr` |
| `batch_ocr_gemini` | native extract → попадает в text-only ветку анализа | уже есть `ocr_text` → text-only анализ | нет `ocr_text` → картинка 1-й страницы → vision (текст+анализ одним вызовом) |
| `batch_analysis_gemini` / `reclassify_*` | текст уже есть → text-only анализ | текст уже есть → text-only анализ | текст уже есть → text-only анализ (сам факт скана роли не играет — важен только `ocr_text`) |
| `recluster` | по `summary`, тип файла не важен | по `summary` | по `summary` |
| Lab (`/lab/:id`) | нет картинки страницы → только текстовые методы актуальны | 1-я страница картинкой | 1-я страница картинкой |

Ключевое правило, которое стоит держать в голове: **все per-document решения
принимаются не по расширению файла напрямую, а по производным полям**
(`ocr_status`, `ocr_text` пусто/не пусто, `vision_status`, есть ли рендер
страницы) — расширение `.docx` лишь на старте определяет, что рендера
страницы не будет никогда.
