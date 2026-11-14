from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.core.config import settings
from app.models.family_account import FamilyAccount
from app.models.monitored_route import MonitoredRoute
from app.models.route_leg import RouteLeg
from app.models.user import User
from app.schemas.monitored_route import (
    MonitoredRouteCreate,
    MonitoredRouteRead,
    MonitoredRouteUpdate,
)
from app.services.scheduler import get_route_scheduler

router = APIRouter()


def _get_route_or_404(db: DbSession, route_id: int) -> MonitoredRoute:
    obj = db.scalar(
        select(MonitoredRoute)
        .options(selectinload(MonitoredRoute.legs))
        .where(MonitoredRoute.id == route_id)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Rota nao encontrada")
    return obj


def _replace_legs(route: MonitoredRoute, legs: list) -> None:
    route.legs.clear()
    for order, leg in enumerate(legs, start=1):
        data = leg.model_dump()
        data["leg_order"] = data.get("leg_order") or order
        route.legs.append(RouteLeg(**data))


@router.get("", response_model=list[MonitoredRouteRead])
def list_routes(
    db: DbSession,
    family_account_id: int | None = Query(None),
    is_active: bool | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(settings.DEFAULT_PAGE_SIZE, ge=1, le=settings.MAX_PAGE_SIZE),
):
    stmt = (
        select(MonitoredRoute)
        .options(selectinload(MonitoredRoute.legs))
        .offset(skip)
        .limit(limit)
        .order_by(MonitoredRoute.id)
    )
    if family_account_id is not None:
        stmt = stmt.where(MonitoredRoute.family_account_id == family_account_id)
    if is_active is not None:
        stmt = stmt.where(MonitoredRoute.is_active == is_active)
    return db.scalars(stmt).all()


@router.post(
    "", response_model=MonitoredRouteRead, status_code=status.HTTP_201_CREATED
)
def create_route(payload: MonitoredRouteCreate, db: DbSession):
    if db.get(FamilyAccount, payload.family_account_id) is None:
        raise HTTPException(status_code=404, detail="Conta familiar nao encontrada")
    if payload.created_by_user_id is not None and (
        db.get(User, payload.created_by_user_id) is None
    ):
        raise HTTPException(status_code=404, detail="Usuario criador nao encontrado")
    data = payload.model_dump(exclude={"legs"})
    obj = MonitoredRoute(**data)
    _replace_legs(obj, payload.legs)
    db.add(obj)
    db.commit()
    get_route_scheduler().sync_route(obj)
    return _get_route_or_404(db, obj.id)


@router.get("/{route_id}", response_model=MonitoredRouteRead)
def get_route(route_id: int, db: DbSession):
    return _get_route_or_404(db, route_id)


@router.patch("/{route_id}", response_model=MonitoredRouteRead)
def update_route(route_id: int, payload: MonitoredRouteUpdate, db: DbSession):
    obj = _get_route_or_404(db, route_id)
    data = payload.model_dump(exclude_unset=True)
    legs = data.pop("legs", None)
    for field, value in data.items():
        setattr(obj, field, value)
    if legs is not None:
        _replace_legs(obj, payload.legs)
    db.commit()
    db.refresh(obj)
    get_route_scheduler().sync_route(obj)
    return _get_route_or_404(db, route_id)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(route_id: int, db: DbSession):
    obj = db.get(MonitoredRoute, route_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Rota nao encontrada")
    db.delete(obj)
    db.commit()
    get_route_scheduler().unschedule_route(route_id)
