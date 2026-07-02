# OCR Lab (`/lab/:id`) — ручной прогон на одном документе

Не таск-очередь, а интерактивный экран для сравнения методов на **первой
странице одного документа**. По умолчанию ничего не пишет в БД. Обычная
документация — [lab-mode.md](../lab-mode.md); здесь только диаграмма решений.

```
открыт /lab/:id
        │
GET /api/lab/methods ──► worker (compute/) доступен? (health-check)
        │                    да ──► ocr_methods = [tesseract, easyocr]
        │                    нет ──► ocr_methods = [tesseract]  (easyocr недоступен)
        │
пользователь жмёт кнопку метода:
        │
   Local OCR (tesseract/easyocr) ──► POST /lab/ocr {doc_id, method}
        │                              работает на 1-й странице (та же картинка,
        │                              что и у Vision — load_first_page)
        │
   AI Vision OCR (provider) ──► POST /lab/vision {doc_id, provider_id}
        │                          провайдер vision-capable, НЕ Mistral?
        │                              да ──► VISION_ANALYSIS_PROMPT →
        │                                       JSON {text, fields{type,date,names,org,amount}}
        │                          провайдер == Mistral OCR? ──► игнорирует prompt,
        │                                       возвращает голый текст;
        │                                       _parse_vision_analysis() мягко
        │                                       откатывается (fields пустые)
        │
   каждый успешный прогон ──► карточка результата (label/kind/chars/ms/cost);
        повторный прогон того же метода ЗАМЕНЯЕТ старую карточку (match по label)
        │
   Judge (premium tier, отдельно настроенный провайдер) ──► POST /lab/judge
        │       {doc_id, provider_id, use_image, candidates[]}
        │
        use_image=true?  ──да──► картинка страницы + ВСЕ транскрипции →
        │                          сравнение с оригиналом (нужен vision-провайдер)
        │                  нет──► только тексты → модель судит связность/читаемость
        │                          (работает с любым premium-провайдером)
        │
        ответ: {rankings[], best, summary, corrected, fields} — победитель
        помечен трофеем в UI
        │
        ▼
   пользователь жмёт 💾 Save на карточке/модалке
        │
        POST /lab/save {doc_id, text, fields?, model_name} ──►
        ЕДИНСТВЕННОЕ место, где Lab пишет в Document:
        ocr_text, fields (если есть), ocr_model=model_name
```

## Отличие от обычного пайплайна

| | Обычная индексация | OCR Lab |
|---|---|---|
| Сколько страниц | все (native/OCR) для полного текста, 1-я — для Vision | всегда только 1-я |
| Пишет в БД | да, автоматически на каждом шаге | нет, пока не нажат Save |
| Статистика провайдера (токены/cost на `AIProvider`) | да | да, даже без Save |
| `.docx` | нативная экстракция текста, работает | нет рендера страницы → только текстовые методы теряют смысл (картинки нет вообще) |
