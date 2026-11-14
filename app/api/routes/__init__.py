from fastapi import APIRouter

from app.api.routes import (
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
api_router.include_router(
    family_accounts.router, prefix="/family-accounts", tags=["family-accounts"]
)
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(
    monitored_routes.router, prefix="/routes", tags=["monitored-routes"]
)
api_router.include_router(
    search_results.router, prefix="/search-results", tags=["search-results"]
)
api_router.include_router(devices.router, prefix="/devices", tags=["devices"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(notifications.router)
api_router.include_router(search.router)
