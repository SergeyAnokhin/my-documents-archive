# Deployment — DocIntel on k3s (ArgoCD + GHCR)

How this repo ships to the home k3s cluster. The **generic platform contract**
(cluster facts, GitOps loop, human-only steps) lives in the read-only
[k3s-platform-deployment.md](k3s-platform-deployment.md) — *don't read/edit it
during normal dev*. This doc records the **DocIntel-specific** mapping onto it.

## GitOps flow

```
push to main ─► GitHub Actions (.github/workflows/build.yml)
                  ├─ build backend + frontend images → GHCR (tag = git SHA)
                  └─ yq-bump image tags in values.yaml → force-push `deploy` branch
                                          │
                ArgoCD watches `deploy` ──┘ → syncs Helm chart → k3s rolls pods
```

ArgoCD tracks the **`deploy`** branch, never `main`. App slug / namespace /
ingress host = **`my-documents-archive`** / `my-documents-archive.local`.
GHCR packages are **public** (no pull secret).

## Files

| File | Role |
|------|------|
| [backend/Dockerfile](../backend/Dockerfile) | Python + Tesseract(rus+fra+eng) + poppler + libmagic. Context = repo root |
| [frontend/Dockerfile](../frontend/Dockerfile) + [nginx.conf](../frontend/nginx.conf) | Vite build → nginx static (SPA fallback) |
| [.dockerignore](../.dockerignore) | Excludes `node_modules`, `library/`, DBs, caches |
| [.github/workflows/build.yml](../.github/workflows/build.yml) | CI: build → GHCR → bump `values.yaml` → push `deploy` |
| [deploy/argocd/application.yaml](../deploy/argocd/application.yaml) | ArgoCD Application (tracks `deploy`) |
| [deploy/helm/my-documents-archive/](../deploy/helm/my-documents-archive/) | Helm chart (see templates below) |

The only file CI mutates is `deploy/helm/my-documents-archive/values.yaml`
(`image.*.tag`).

## DocIntel-specific adaptations

| Concern | Decision | Why |
|---|---|---|
| API prefix | `ingress.stripApiPrefix: false` | Backend already serves routes at `/api/...` — do **not** strip |
| Ingress paths | `/api` + `/thumbnails` → backend, `/` → frontend | Backend also mounts static `/thumbnails` (see [main.py](../backend/app/main.py)) |
| Health probe | `/api/health` | Readiness gate for ArgoCD health |
| Backend scaling | single replica, `strategy: Recreate` | Stateful, node-pinned PVC |
| OCR worker | **not deployed** | Tesseract baked into backend image; `compute/` skipped |

## Storage — nested-mount layout (no code change)

`config.py` derives `.docintell/` from `library_path`, so to keep the DB off
CIFS we overlay it with a second mount:

```
LIBRARY_PATH = /data/library
  ├─ SMB CSI (NAS //192.168.1.91/Data/my-documents-archive, RW) → /data/library
  └─ local-path PVC                                              → /data/library/.docintell
```

- **NAS** holds the source documents (read/written in place; backfill existing
  files via Admin → **Sync**, since the watcher is non-recursive + new-files-only).
- **local-path PVC** holds derived state: SQLite, ChromaDB, thumbnails, HF model
  cache (`HF_HOME`) — fast and safe (no CIFS file-locking).

Templates: [backend-deployment.yaml](../deploy/helm/my-documents-archive/templates/backend-deployment.yaml),
[smb-nas.yaml](../deploy/helm/my-documents-archive/templates/smb-nas.yaml),
[state-pvc.yaml](../deploy/helm/my-documents-archive/templates/state-pvc.yaml),
[ingress.yaml](../deploy/helm/my-documents-archive/templates/ingress.yaml).

## DB backup & restore

A **sidecar** ([backup.py](../backend/backup.py)) in the backend pod copies the
SQLite DB from the local PVC to the NAS document root every `intervalSeconds`
(default 300), only when the DB changed, rotating the `keep` newest copies
(`docintell.db.backup.1` = newest, `.2` = previous). Configured via
`backend.backup.*` in `values.yaml`; `BACKUP_DIR`/`BACKUP_PREFIX` are passed to
**both** the sidecar and the backend container so list/restore stay in sync.

**Restore** (advanced-mode UI: Admin → **Backup** tab): lists snapshots and
restores one. Backend [services/db_backup.py](../backend/app/services/db_backup.py)
takes a `docintell.db.pre-restore` safety snapshot, then does an atomic swap.
Endpoints in [routers/admin_backups.py](../backend/app/routers/admin_backups.py)
(see [api.md](api.md)); pinned by [test_db_backup.py](../backend/tests/test_db_backup.py).
After a restore the user reloads the page.

## Human-only steps

Все команды ниже выполняются **один раз** на машине с доступом к кластеру (`kubectl`).
Общий контракт платформы — [k3s-platform-deployment.md §6](k3s-platform-deployment.md#6-human-only-checklist-cannot-be-done-by-the-agent).

### Шаг 1 — Первый билд и публичность пакетов GHCR

1. Сделай любой коммит в `main` (например, пустой `git commit --allow-empty`) или
   запусти workflow вручную: GitHub → Actions → **build-and-push** → Run workflow.
2. Дождись зелёного результата — GitHub Actions создаст ветку `deploy` и
   запушит образы в GHCR.
3. Сделай оба образа публичными (иначе кластер не сможет их скачать без pull-secret):
   - GitHub → репозиторий → **Packages** (правая колонка или вкладка)
   - Открой `my-documents-archive/backend` → Package settings → **Change visibility → Public**
   - Повтори для `my-documents-archive/frontend`

### Шаг 2 — Установка SMB CSI driver (если ещё не стоит)

```bash
# Проверить, не установлен ли уже:
kubectl -n kube-system get pods | grep csi-smb

# Если нет — установить:
helm repo add csi-driver-smb https://raw.githubusercontent.com/kubernetes-csi/csi-driver-smb/master/charts
helm repo update
helm install csi-driver-smb csi-driver-smb/csi-driver-smb \
  --namespace kube-system \
  --set controller.replicas=1
```

### Шаг 3 — Создание namespace и секрета с NAS-кредами

```bash
# Namespace создаёт ArgoCD автоматически, но для секрета он нужен заранее:
kubectl create namespace my-documents-archive

# SMB-кред: пользователь и пароль из Synology (тот, что ты создал для шары my-documents-archive)
kubectl create secret generic my-documents-archive-smb-creds \
  -n my-documents-archive \
  --from-literal=username=my-doc \
  --from-literal=password=<ПАРОЛЬ_ИЗ_SYNOLOGY>
```

> Пароль вводи прямо в терминале — никогда не сохраняй в файлах в репозитории.

### Шаг 4 — Регистрация приложения в ArgoCD

```bash
kubectl apply -f deploy/argocd/application.yaml

# Подождать синхронизации (занимает ~1 минуту):
kubectl -n argocd get application my-documents-archive
# Ожидаемый результат: STATUS=Synced  HEALTH=Healthy
```

Или открой ArgoCD UI (обычно `https://<node-ip>:30443` или `https://argocd.local`)
и проверь, что приложение `my-documents-archive` появилось и перешло в `Healthy`.

### Шаг 5 — DNS / hosts

На каждой машине, с которой хочешь открывать приложение, добавь строку в `hosts`
(`C:\Windows\System32\drivers\etc\hosts` на Windows, `/etc/hosts` на Linux/Mac):

```
192.168.1.X  my-documents-archive.local
```

где `192.168.1.X` — IP любого узла кластера (Traefik слушает на всех нодах).
Можно узнать: `kubectl get nodes -o wide`.

После этого открывай: **http://my-documents-archive.local**

### Шаг 6 — Первичная синхронизация существующих документов

Watcher работает в режиме «только новые файлы»; существующие документы на NAS
**не подберутся автоматически**. Чтобы проиндексировать то, что уже лежит на шаре:

Открой UI → **Администрирование** → вкладка **Индексирование** → кнопка **Синхронизировать**.

### Проверка после деплоя

```bash
# Поды Running?
kubectl -n my-documents-archive get pods -o wide

# PVC примонтированы?
kubectl -n my-documents-archive get pvc

# Ingress зарегистрирован?
kubectl -n my-documents-archive get ingress

# Логи backend:
kubectl -n my-documents-archive logs deploy/my-documents-archive-backend

# Логи sidecar-бэкапа:
kubectl -n my-documents-archive logs deploy/my-documents-archive-backend -c db-backup
```

| Симптом | Вероятная причина |
|---|---|
| `ImagePullBackOff` | Пакет GHCR ещё приватный — сделай публичным (Шаг 1) |
| PVC `Pending` | SMB CSI driver не установлен, или IP/путь NAS неверный |
| Нет доступа к NAS | Секрет с кредами не создан, или пароль неверный |
| 404 на `/api/*` | Ingress не создан или Traefik перезапускается |
| ArgoCD не синкается | Ветка `deploy` ещё не создана — запусти билд вручную (Шаг 1) |
