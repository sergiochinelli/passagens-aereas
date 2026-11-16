from fastapi import APIRouter, Depends

from app.api.deps import require_auth
from app.api.routes import (
    auth,
    devices,
    family_accounts,
    monitored_routes,
    notifications,
    search,
    search_results,
    settings,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])

_guard = [Depends(require_auth)]
api_router.include_router(
    family_accounts.router,
    prefix="/family-accounts",
    tags=["family-accounts"],
    dependencies=_guard,
)
api_router.include_router(
    users.router, prefix="/users", tags=["users"], dependencies=_guard
)
api_router.include_router(
    monitored_routes.router,
    prefix="/routes",
    tags=["monitored-routes"],
    dependencies=_guard,
)
api_router.include_router(
    search_results.router,
    prefix="/search-results",
    tags=["search-results"],
    dependencies=_guard,
)
api_router.include_router(
    devices.router, prefix="/devices", tags=["devices"], dependencies=_guard
)
api_router.include_router(
    settings.router, prefix="/settings", tags=["settings"], dependencies=_guard
)
api_router.include_router(notifications.router, dependencies=_guard)
api_router.include_router(search.router, dependencies=_guard)
