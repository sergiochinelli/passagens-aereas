"""Testes funcionais da Etapa 3 - Agendador APScheduler.

O scheduler roda em modo "stopped" nos testes: os jobs sao inspecionados
via API do APScheduler (get_job/get_jobs) sem disparo real. A execucao do
job e testada invocando run_route_check com servico mockado.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.main import app
from app.api.deps import get_flight_search_service
from app.models.monitored_route import MonitoredRoute
from app.models.route_leg import RouteLeg
from app.services.flight_search import FlightSearchService
from app.services.scheduler import (
    RouteScheduler,
    get_route_scheduler,
    job_id_for,
    reset_route_scheduler,
    run_route_check,
)
from app.services.serpapi_client import SerpApiClient, SerpApiError

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def fresh_scheduler():
    """Scheduler global limpo entre testes (nao iniciado)."""
    reset_route_scheduler()
    yield
    reset_route_scheduler()


def _route(
    route_id=None, is_active=True, interval=30, trip_type="round_trip", **kw
) -> MonitoredRoute:
    route = MonitoredRoute(
        family_account_id=1,
        trip_type=trip_type,
        origin="GRU",
        destination="MIA",
        departure_date=date(2026, 12, 10),
        return_date=date(2026, 12, 20),
        passengers=1,
        travel_class="economy",
        monitor_interval_minutes=interval,
        is_active=is_active,
        **kw,
    )
    if route_id is not None:
        route.id = route_id
    return route


# ----------------------- ciclo de vida do job -------------------

def test_schedule_route_creates_interval_job():
    scheduler = RouteScheduler()
    scheduler.schedule_route(_route(route_id=7, interval=45))

    job = scheduler.get_job(7)
    assert job is not None
    assert job.id == job_id_for(7)
    assert job.trigger.interval == timedelta(minutes=45)


def test_sync_route_updates_existing_job():
    scheduler = RouteScheduler()
    scheduler.schedule_route(_route(route_id=3, interval=30))
    scheduler.sync_route(_route(route_id=3, interval=120))

    job = scheduler.get_job(3)
    assert job is not None
    assert job.trigger.interval == timedelta(minutes=120)


def test_sync_route_removes_job_when_inactive():
    scheduler = RouteScheduler()
    scheduler.schedule_route(_route(route_id=4, interval=30))
    scheduler.sync_route(_route(route_id=4, is_active=False, interval=30))

    assert scheduler.get_job(4) is None


def test_unschedule_nonexistent_route_is_noop():
    scheduler = RouteScheduler()
    scheduler.unschedule_route(999)  # nao levanta excecao


def test_load_active_routes_schedules_only_active(db):
    active = _route(interval=15)
    inactive = _route(interval=15, is_active=False)
    db.add_all([active, inactive])
    db.commit()

    scheduler = RouteScheduler()
    count = scheduler.load_active_routes(db)

    assert count >= 1
    assert scheduler.get_job(active.id) is not None
    assert scheduler.get_job(inactive.id) is None


# ----------------------- execucao do job ------------------------

def test_run_route_check_executes_search(db, monkeypatch):
    calls = {}

    class _FakeService:
        def search_route(self, session, route, triggered_by):
            calls["route_id"] = route.id
            calls["triggered_by"] = triggered_by

    monkeypatch.setattr(
        "app.services.scheduler.FlightSearchService", lambda: _FakeService()
    )

    route = _route(interval=30)
    db.add(route)
    db.commit()

    run_route_check(route.id, session_factory=lambda: db)
    assert calls == {"route_id": route.id, "triggered_by": "scheduled"}


def test_run_route_check_removes_job_for_inactive_route(db, monkeypatch):
    class _FakeService:
        def search_route(self, *a, **kw):
            raise AssertionError("nao deveria buscar rota inativa")

    monkeypatch.setattr(
        "app.services.scheduler.FlightSearchService", lambda: _FakeService()
    )

    route = _route(interval=30, is_active=False)
    db.add(route)
    db.commit()

    scheduler = get_route_scheduler()
    scheduler.schedule_route(route)
    run_route_check(route.id, session_factory=lambda: db)

    assert scheduler.get_job(route.id) is None


def test_run_route_check_serpapi_error_does_not_raise(db, monkeypatch):
    class _FailService:
        def search_route(self, *a, **kw):
            raise SerpApiError("quota excedida")

    monkeypatch.setattr(
        "app.services.scheduler.FlightSearchService", lambda: _FailService()
    )

    route = _route(interval=30)
    db.add(route)
    db.commit()

    run_route_check(route.id, session_factory=lambda: db)  # nao levanta


# --------------------- sincronizacao via CRUD --------------------

def test_crud_lifecycle_syncs_scheduler(client, family_account):
    scheduler = get_route_scheduler()

    payload = {
        "family_account_id": family_account["id"],
        "trip_type": "round_trip",
        "origin": "GRU",
        "destination": "MIA",
        "departure_date": "2026-12-10",
        "return_date": "2026-12-20",
        "monitor_interval_minutes": 20,
    }
    resp = client.post(f"{API}/routes", json=payload)
    assert resp.status_code == 201
    route_id = resp.json()["id"]
    assert scheduler.get_job(route_id) is not None
    assert scheduler.get_job(route_id).trigger.interval == timedelta(minutes=20)

    # PATCH altera intervalo -> job reagendado
    resp = client.patch(
        f"{API}/routes/{route_id}", json={"monitor_interval_minutes": 90}
    )
    assert resp.status_code == 200
    assert scheduler.get_job(route_id).trigger.interval == timedelta(minutes=90)

    # PATCH desativa -> job removido
    resp = client.patch(f"{API}/routes/{route_id}", json={"is_active": False})
    assert resp.status_code == 200
    assert scheduler.get_job(route_id) is None

    # DELETE -> job removido
    client.patch(f"{API}/routes/{route_id}", json={"is_active": True})
    assert scheduler.get_job(route_id) is not None
    client.delete(f"{API}/routes/{route_id}")
    assert scheduler.get_job(route_id) is None


# ------------------ endpoints: trigger e status -----------------

def test_trigger_endpoint_persists_manual_result(client, family_account):
    class _FakeClient(SerpApiClient):
        def search(self, params):
            return json.loads(
                (FIXTURES / "serpapi_round_trip.json").read_text("utf-8")
            )

    app.dependency_overrides[get_flight_search_service] = (
        lambda: FlightSearchService(_FakeClient())
    )
    try:
        resp = client.post(
            f"{API}/routes",
            json={
                "family_account_id": family_account["id"],
                "trip_type": "round_trip",
                "origin": "GRU",
                "destination": "MIA",
                "departure_date": "2026-12-10",
                "return_date": "2026-12-20",
            },
        )
        route_id = resp.json()["id"]

        resp = client.post(f"{API}/routes/{route_id}/trigger")
        assert resp.status_code == 201, resp.text
        assert resp.json()["triggered_by"] == "manual"
        assert resp.json()["lowest_price"] is not None
    finally:
        app.dependency_overrides.pop(get_flight_search_service, None)


def test_scheduler_status_endpoint(client):
    scheduler = get_route_scheduler()
    scheduler.schedule_route(_route(route_id=50, interval=60))

    resp = client.get(f"{API}/scheduler/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is False  # nao iniciado em testes
    route_ids = [j["route_id"] for j in body["jobs"]]
    assert 50 in route_ids
