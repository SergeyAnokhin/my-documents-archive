"""Admin API aggregator — mounts the split sub-routers under /api/admin.

The endpoints live in focused modules so each concern is easy to find:
  - admin_library.py    stats, sync, batch indexing, reclassify, log
  - admin_folders.py    watched folders CRUD
  - admin_providers.py  AI providers CRUD + model listing + arena ratings
  - admin_settings.py   app settings key-value store
"""
from fastapi import APIRouter

from . import admin_library, admin_folders, admin_providers, admin_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])
router.include_router(admin_library.router)
router.include_router(admin_folders.router)
router.include_router(admin_providers.router)
router.include_router(admin_settings.router)
