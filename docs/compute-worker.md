# Compute Worker (OCR Microservice)

The compute worker is an **optional** external FastAPI service (`compute/`) that adds
EasyOCR support and can offload heavy OCR to a separate machine. Tesseract OCR works
without it (runs in-process on the backend). The worker is needed only when you want
EasyOCR as an additional recognition engine in the OCR Lab.

## Architecture

```
backend (port 8000)
  ↓ GET {ocr_worker_url}/health     (when admin checks status)
  ↓ POST {ocr_worker_url}/ocr       (when lab runs easyocr)
compute worker (port 8001)
  └─ /health  → { engines: ["tesseract", "easyocr"], ... }
  └─ /ocr?engine=tesseract|easyocr|auto  → { text, pages, engine }
```

The worker URL is stored in `AppSettings.ocr_worker_url` and set from
Admin → Indexing → Compute Worker.

## Installation

### All platforms (base)

```bash
cd compute
pip install -r requirements.txt
```

### Windows + Miniforge/Conda — critical extra step

On Windows with a **conda-based Python** (miniforge, miniconda, anaconda), conda
installs numpy/scipy/scikit-image linked against **OpenBLAS**, while pip-installed
PyTorch uses **MKL**. When both are loaded in the same process, the DLL conflict
causes a native crash (exit code `3228369023`, undetectable by `except Exception`).

**Fix — reinstall these packages from pip AFTER requirements.txt:**

```powershell
pip install -r requirements.txt
pip install numpy scipy scikit-image --force-reinstall
```

The pip wheels use MKL (same as torch), eliminating the conflict. This is safe —
pip versions replace the conda ones in the active environment.

**Dependency conflicts** from other conda packages (demucs, openunmix, openvino)
may appear in pip output — they are pre-existing and do not affect the worker.

### Pillow ≥10 compatibility

EasyOCR's `utils.py` references `PIL.Image.ANTIALIAS`, which was removed in
Pillow 10.0.0 (replaced by `PIL.Image.LANCZOS`). The worker monkey-patches this
at call time (`_easyocr()` in `compute/app/main.py`) — no manual fix needed.
Symptom if the patch is missing: `AttributeError: module 'PIL.Image' has no attribute 'ANTIALIAS'`.

### EasyOCR first run

The first time `easyocr.Reader` is created it downloads detection + recognition
models (~100 MB). This happens automatically when the lab runs its first EasyOCR
request, not at startup.

## Running

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

From `npm run dev` (repo root) the worker starts automatically via concurrently.

## Connecting from the admin panel

In Admin → Indexing → Compute Worker enter:

```
http://localhost:8001
```

> **Do not use `http://0.0.0.0:8001`** — that is the bind address, not a valid
> connection target. On Windows, connecting to `0.0.0.0` fails silently.

Click **Tesseract** or **EasyOCR** to probe the worker. The UI shows:
- Pulsing green dot + "Сервис доступен" — worker is reachable
- Green/red pill per engine — which engines are available

## Engine detection (`_probe`)

At startup, `compute/app/main.py` checks engine availability once via a **subprocess**:

```python
def _probe(module: str) -> bool:
    r = subprocess.run([sys.executable, "-c", f"import {module}"], ...)
    return r.returncode == 0
```

This isolates native DLL crashes (common with easyocr/torch on Windows) from the
main uvicorn process. If `import easyocr` crashes in the subprocess, the worker
continues running and reports `easyocr=False`.

Tesseract is probed in-process (safe) via `pytesseract.get_tesseract_version()`.

Startup log line: `[ocr-worker] engines: tesseract=True, easyocr=True`

## Endpoints

| Method | Path | Params | Returns |
|--------|------|--------|---------|
| GET | `/health` | — | `{ status, engines[], languages }` |
| POST | `/ocr` | file (multipart), `engine`, `languages` | `{ text, pages, engine }` |

`engine` choices: `tesseract` · `easyocr` · `auto` (tries easyocr, falls back to tesseract).

Languages default to `OCR_LANGUAGES` env var (`rus+fra+eng`). Tesseract uses `+`
separator, EasyOCR uses 2-letter codes (`ru,fr,en`) — the worker converts automatically.

**EasyOCR Cyrillic constraint:** EasyOCR's Cyrillic model is only compatible with
English — not other Latin-script languages (French, German, etc.). When the language
list contains any Cyrillic language (`ru`, `be`, `bg`, `uk`, `mn`), the worker
automatically drops non-English Latin languages. e.g. `rus+fra+eng` → `["ru","en"]`.
Tesseract is unaffected and handles all requested languages.

## OCR Lab integration

`GET /api/lab/methods` in the backend probes the worker and returns which OCR methods
are available. The Lab page shows a Run button per method — only methods returned by
this endpoint appear. If the worker is down, only `tesseract` (in-process) shows.

See [lab-mode.md](lab-mode.md) for the full lab flow.

## Запуск на dev-машине при k8s-деплое

Если основной стек (`backend` + `frontend`) развёрнут в Kubernetes, compute-воркер
можно запускать на локальной Windows-машине разработчика — это даёт доступ к EasyOCR
без выделенной ноды в кластере.

### 1. Запустить воркер

```powershell
npm run compute
```

При старте в консоль выводится LAN-адрес, который нужно вставить в UI:

```
  Compute worker → http://192.168.1.X:8001
```

### 2. Открыть порт в Windows Firewall (один раз, от администратора)

```powershell
netsh advfirewall firewall add rule `
  name="DocIntel compute worker" `
  dir=in action=allow protocol=TCP localport=8001
```

### 3. Узнать LAN-адрес машины

```powershell
ipconfig | findstr "IPv4"
```

Запомни адрес вида `192.168.1.X`.

### 4. Подключить в UI

Открой `http://my-documents-archive.lan` → **Admin → Indexing → Compute Worker**,
вставь URL:

```
http://192.168.1.X:8001
```

Статус проверяется автоматически через ~0,7 с после вставки — должен появиться
зелёный индикатор. Нажми **Save** для сохранения.

> Если воркер не запущен, backend продолжает работу с Tesseract из образа — EasyOCR
> просто не появляется в OCR Lab.
