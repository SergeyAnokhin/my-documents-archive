from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .config import settings
from .database import init_db
from .routers import documents, upload, search, admin, indexing, lab
from .routers.tasks import router as tasks_router

app = FastAPI(
    title="DocIntel API",
    version=settings.app_version,
    description="Smart Search System for Personal Document Archives",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(upload.router)
app.include_router(search.router)
app.include_router(admin.router)
app.include_router(indexing.router)
app.include_router(lab.router)
app.include_router(tasks_router)


@app.on_event("startup")
def on_startup():
    init_db()
    settings.thumbnails_dir.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def mount_thumbnails():
    thumb_dir = settings.thumbnails_dir
    thumb_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/thumbnails", StaticFiles(directory=str(thumb_dir)), name="thumbnails")


@app.on_event("startup")
def start_folder_watcher():
    from .services.watcher import watcher
    watcher.start()


@app.on_event("shutdown")
def stop_folder_watcher():
    from .services.watcher import watcher
    watcher.stop()


@app.get("/api/health")
def health():
    return {"status": "ok", "version": settings.app_version}
