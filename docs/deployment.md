# Deployment — DocIntel on k3s (ArgoCD + GHCR)

How this repo ships to the home k3s cluster. The **generic platform contract**
(cluster facts, GitOps loop, human-only steps) lives in the read-only
[excluded-from-analysis/k3s-platform-deployment.md](excluded-from-analysis/k3s-platform-deployment.md) — *don't read/edit it
during normal dev*. This doc records the **DocIntel-specific** mapping onto it.

## GitOps flow

```
push to main ─► GitHub Actions (.github/workflows/build.yml)
                  ├─ build backend + frontend images → GHCR (tag = git SHA)
                  └─ yq-bump image tags in values.yaml → force-push `deploy` branch
                                          │
                ArgoCD watches `deploy` ──┘ → syncs Helm chart → k3s rolls pods
```

ArgoCD tracks the **`deploy`** branch, never `main`. App slug / namespace =
**`my-documents-archive`**; ingress host = `my-documents-archive.192.168.1.97.nip.io`
(HTTPS via cert-manager `home-ca`). GHCR packages are **public** (no pull secret).

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
(default 300), only when the DB changed, rotating the newest N copies
(`docintell.db.backup.1` = newest, `.2` = previous, ...). `intervalSeconds` is
still deploy-time only, via `backend.backup.*` in `values.yaml`. N (how many
to keep) is now **runtime-configurable** from the admin Backup tab — it reads
and writes the `backup_keep` row in `app_settings`, which the sidecar re-reads
on every run; `backend.backup.keep` in `values.yaml` (env `BACKUP_KEEP`) is
only the initial/fallback value used until that row is set. `BACKUP_DIR`/
`BACKUP_PREFIX` are passed to **both** the sidecar and the backend container
so list/restore stay in sync.

**Restore** (advanced-mode UI: Admin → **Backup** tab): lists snapshots and
restores one. Backend [services/db_backup.py](../backend/app/services/db_backup.py)
takes a `docintell.db.pre-restore` safety snapshot, then does an atomic swap.
Endpoints in [routers/admin_backups.py](../backend/app/routers/admin_backups.py)
(see [api.md](api.md)); pinned by [test_db_backup.py](../backend/tests/test_db_backup.py).
After a restore the user reloads the page.

## Human-only steps

All commands below are executed **once** on a machine with cluster access (`kubectl`).
Generic platform contract — [excluded-from-analysis/k3s-platform-deployment.md §6](excluded-from-analysis/k3s-platform-deployment.md#6-human-only-checklist-cannot-be-done-by-the-agent).

### Step 1 — First build and making GHCR packages public

1. Make any commit to `main` (e.g. an empty `git commit --allow-empty`) or
   trigger the workflow manually: GitHub → Actions → **build-and-push** → Run workflow.
2. Wait for a green result — GitHub Actions will create the `deploy` branch and
   push images to GHCR.
3. Make both images public (otherwise the cluster cannot pull them without a pull secret):
   - GitHub → repository → **Packages** (right sidebar or tab)
   - Open `my-documents-archive/backend` → Package settings → **Change visibility → Public**
   - Repeat for `my-documents-archive/frontend`

### Step 2 — Install SMB CSI driver (if not already installed)

```bash
# Check if already installed:
kubectl -n kube-system get pods | grep csi-smb

# If not — install:
helm repo add csi-driver-smb https://raw.githubusercontent.com/kubernetes-csi/csi-driver-smb/master/charts
helm repo update
helm install csi-driver-smb csi-driver-smb/csi-driver-smb \
  --namespace kube-system \
  --set controller.replicas=1
```

### Step 3 — Create namespace and NAS credentials secret

```bash
# ArgoCD creates the namespace automatically, but the secret needs it in advance:
kubectl create namespace my-documents-archive

# SMB credentials: username and password from Synology (created for the my-documents-archive share)
kubectl create secret generic my-documents-archive-smb-creds \
  -n my-documents-archive \
  --from-literal=username=my-doc \
  --from-literal=password=<SYNOLOGY_PASSWORD>
```

> Enter the password directly in the terminal — never save it in repository files.

### Step 4 — Register the application in ArgoCD

```bash
kubectl apply -f deploy/argocd/application.yaml

# Wait for sync (~1 minute):
kubectl -n argocd get application my-documents-archive
# Expected result: STATUS=Synced  HEALTH=Healthy
```

Or open the ArgoCD UI (usually `https://<node-ip>:30443` or `https://argocd.local`)
and verify that the `my-documents-archive` application appears and transitions to `Healthy`.

### Step 5 — DNS and access from mobile devices

**Default method — nip.io (no router configuration needed):**

nip.io is a public DNS service: `anything.<IP>.nip.io` always resolves to `<IP>`
via standard DNS. No hosts file or router configuration required.
Works on phones, tablets, and any device.

> **Why router DNS doesn't work on mobile:** Android 9+ and iOS 14+ use
> DNS-over-HTTPS (Google/Cloudflare), bypassing the router's DNS. So even a correctly
> configured router (`my-documents-archive.lan` → `192.168.1.97`) is ignored by phones.
> nip.io solves this through public DNS.

Cluster: `k3s` (192.168.1.97). Host is already set in `values.yaml`:

```
my-documents-archive.192.168.1.97.nip.io   → DocIntel (this project)
otherapp.192.168.1.97.nip.io               → another project (example)
```

Traefik routes them by Host header; same port (80 or 443).

Open from any device on the home WiFi:
**http://my-documents-archive.192.168.1.97.nip.io**
(or https:// after setting up cert-manager below)

> **nip.io limitation:** requires internet access for DNS resolution.
> If WiFi has no internet — use a hosts file entry as a fallback.

**Fallback — hosts file (PC/Mac only, does not work on mobile):**

```
# C:\Windows\System32\drivers\etc\hosts  (Windows)
# /etc/hosts  (Linux/Mac)
192.168.1.97  my-documents-archive.192.168.1.97.nip.io
```

### Step 5a — HTTPS with automatic certificate renewal (optional)

After completing Step 5, HTTPS can be configured. Certificates are issued and renewed
by **cert-manager** — no manual intervention ever needed.

The approach: a local CA (root certificate) is created, installed on the device
**once**, and cert-manager issues TLS certificates from it for all applications and
renews them automatically (by default 30 days before expiry).

#### 5a.1 — Install cert-manager

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
kubectl -n cert-manager rollout status deploy/cert-manager   # wait ~1 min
```

#### 5a.2 — Create local CA

```bash
kubectl apply -f deploy/k8s/cert-manager/home-ca.yaml
# Verify ClusterIssuer is ready:
kubectl get clusterissuer home-ca
```

#### 5a.3 — Install CA certificate on device

```bash
# Export CA to file:
kubectl get secret home-ca-secret -n cert-manager \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > home-ca.crt
```

- **iPhone:** send `home-ca.crt` by email or AirDrop →
  Settings → General → VPN & Device Management → tap the profile → Install →
  then Settings → General → About → Certificate Trust Settings →
  enable "Home K3s CA".
- **Android:** Settings → Security → Install certificate →
  CA certificate → select `home-ca.crt`.

#### 5a.4 — Enable TLS in values.yaml (already enabled by default)

Confirm that `values.yaml` contains:
```yaml
ingress:
  tls: true
  certIssuer: home-ca
```

Push to `main` → ArgoCD picks it up → cert-manager issues the certificate (~30 sec).

#### 5a.5 — Verify HTTPS

```bash
# Certificate issued?
kubectl -n my-documents-archive get certificate
# Expected: READY=True

# TLS secret created?
kubectl -n my-documents-archive get secret my-documents-archive-tls
```

Open `https://my-documents-archive.192.168.1.97.nip.io` on the phone — the padlock
should be closed with no warnings.

### Step 6 — Initial sync of existing documents

The watcher runs in "new files only" mode; existing documents on the NAS
**will not be picked up automatically**. To index files already on the share:

Open UI → **Admin** → **Indexing** tab → click **Sync**.

### Post-deploy verification

```bash
# Pods Running?
kubectl -n my-documents-archive get pods -o wide

# PVCs mounted?
kubectl -n my-documents-archive get pvc

# Ingress registered?
kubectl -n my-documents-archive get ingress

# Backend logs:
kubectl -n my-documents-archive logs deploy/my-documents-archive-backend

# Backup sidecar logs:
kubectl -n my-documents-archive logs deploy/my-documents-archive-backend -c db-backup
```

| Symptom | Likely cause |
|---|---|
| `ImagePullBackOff` | GHCR package still private — make it public (Step 1) |
| PVC `Pending` | SMB CSI driver not installed, or NAS IP/path is wrong |
| No NAS access | Credentials secret not created, or password is wrong |
| 404 on `/api/*` | Ingress not created or Traefik restarting |
| ArgoCD not syncing | `deploy` branch not yet created — trigger build manually (Step 1) |
| nip.io not resolving | No internet access on device; use hosts file as fallback |
| HTTPS: certificate not issued (`READY=False`) | cert-manager not installed, or `home-ca.yaml` not applied |
| HTTPS: browser shows warning | CA certificate (`home-ca.crt`) not installed on device (Step 5a.3) |
