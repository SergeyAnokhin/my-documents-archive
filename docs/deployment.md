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

One-time cluster setup (cluster + GitHub-admin access) is the spec's §6 checklist:
first build → make GHCR packages public → install SMB CSI driver → create the
`my-documents-archive-smb-creds` secret (keys `username`/`password`) →
`kubectl apply` the ArgoCD Application → add `my-documents-archive.local` to DNS/hosts.
