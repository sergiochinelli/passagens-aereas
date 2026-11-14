from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.config import settings
from app.models.monitored_route import MonitoredRoute
from app.models.search_result import SearchResult
from app.schemas.search_result import SearchResultCreate, SearchResultRead

router = APIRouter()


@router.get("", response_model=list[SearchResultRead])
def list_results(
    db: DbSession,
    route_id: int | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(settings.DEFAULT_PAGE_SIZE, ge=1, le=settings.MAX_PAGE_SIZE),
):
    stmt = (
        select(SearchResult)
        .offset(skip)
        .limit(limit)
        .order_by(SearchResult.searched_at.desc())
    )
    if route_id is not None:
        stmt = stmt.where(SearchResult.route_id == route_id)
    return db.scalars(stmt).all()


@router.post(
    "", response_model=SearchResultRead, status_code=status.HTTP_201_CREATED
)
def create_result(payload: SearchResultCreate, db: DbSession):
    if db.get(MonitoredRoute, payload.route_id) is None:
        raise HTTPException(status_code=404, detail="Rota nao encontrada")
    obj = SearchResult(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{result_id}", response_model=SearchResultRead)
def get_result(result_id: int, db: DbSession):
    obj = db.get(SearchResult, result_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Resultado nao encontrado")
    return obj


@router.delete("/{result_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_result(result_id: int, db: DbSession):
    obj = db.get(SearchResult, result_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Resultado nao encontrado")
    db.delete(obj)
    db.commit()
