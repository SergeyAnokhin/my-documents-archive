# DocIntel — Smart Document Archive

Семейный архив документов с умным поиском. Загружайте, находите, систематизируйте.

## Быстрый старт

```bash
# Бэкенд
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Фронтенд
cd frontend
npm install
npm run dev
```

Открыть в браузере: http://localhost:5173

## Документация

| Документ | Описание |
|----------|----------|
| [`docs/First_Specification.md`](docs/First_Specification.md) | Полная спецификация проекта |
| [`docs/code-map.md`](docs/code-map.md) | Карта кода — где что лежит |
| [`AGENTS.md`](AGENTS.md) | Гид для AI-ассистентов |

## Технологии

- **Backend:** FastAPI + SQLAlchemy + SQLite
- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **Языки:** Русский, English (i18n)
- **Дизайн:** Anthropic-стиль, чёрно-белый, минималистичный

## Фазы разработки

- [x] Фаза 1 — Foundation (загрузка, просмотр, базовая структура)
- [x] Фаза 2 — OCR + полнотекстовый поиск + миниатюры
- [ ] Фаза 3 — AI-анализ (теги, описание, тип)
- [ ] Фаза 4 — AI Vision + семантический поиск
- [ ] Фаза 5 — Мониторинг папок + batch-индексация
- [ ] Фаза 6 — Developer Mode + админ-интерфейс
- [ ] Фаза 7 — Внешний OCR-сервис
