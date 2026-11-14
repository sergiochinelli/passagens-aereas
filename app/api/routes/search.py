from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, FlightService
from app.core.config import settings
from app.models.monitored_route import MonitoredRoute
from app.schemas.flight_search import (
    FlightSearchResponse,
    SearchCriteria,
)
from app.schemas.search_result import SearchResultRead
from app.services.scheduler import get_route_scheduler
from app.services.serpapi_client import SerpApiError

router = APIRouter()


@router.post(
    "/search",
    response_model=FlightSearchResponse,
    status_code=status.HTTP_200_OK,
    tags=["search"],
)
def search_flights(criteria: SearchCriteria, service: FlightService):
    """Busca avulsa de passagens (nao persiste; usada pela tela de busca)."""
    try:
        return service.search(criteria)
    except SerpApiError as exc:
        raise HTTPException(
            status_code=exc.status_code or 503, detail=str(exc)
        ) from exc


def _run_route_search(route_id: int, db: DbSession, service) -> SearchResultRead:
    route = db.scalar(
        select(MonitoredRoute)
        .options(selectinload(MonitoredRoute.legs))
        .where(MonitoredRoute.id == route_id)
    )
    if route is None:
        raise HTTPException(status_code=404, detail="Rota nao encontrada")
    try:
        return service.search_route(db, route, triggered_by="manual")
    except SerpApiError as exc:
        raise HTTPException(
            status_code=exc.status_code or 503, detail=str(exc)
        ) from exc


@router.post(
    "/routes/{route_id}/search",
    response_model=SearchResultRead,
    status_code=status.HTTP_201_CREATED,
    tags=["monitored-routes"],
)
def trigger_route_search(route_id: int, db: DbSession, service: FlightService):
    """Disparo manual de consulta para uma rota monitorada; persiste o resultado."""
    return _run_route_search(route_id, db, service)


@router.post(
    "/routes/{route_id}/trigger",
    response_model=SearchResultRead,
    status_code=status.HTTP_201_CREATED,
    tags=["monitored-routes"],
)
def trigger_route_now(route_id: int, db: DbSession, service: FlightService):
    """Disparo manual imediato (alias oficial do monitoramento por demanda)."""
    return _run_route_search(route_id, db, service)


@router.get("/scheduler/status", tags=["scheduler"])
def scheduler_status():
    """Lista os jobs agendados e a proxima execucao de cada rota."""
    scheduler = get_route_scheduler()
    return {
        "enabled": settings.SCHEDULER_ENABLED,
        "running": scheduler.running,
        "jobs": scheduler.list_jobs(),
    }
