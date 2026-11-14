"""Testes funcionais da Etapa 2 - Integracao SerpApi (Google Flights).

A camada HTTP e substituida por httpx.MockTransport: nenhuma chamada de rede
real e feita. Os fixtures em tests/fixtures reproduzem respostas reais da
SerpApi (engine google_flights).
"""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.api.deps import get_flight_search_service
from app.main import app
from app.schemas.flight_search import SearchCriteria
from app.services.flight_search import FlightSearchService, criteria_from_route
from app.services.serpapi_client import SerpApiClient, SerpApiError

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _criteria(**overrides) -> SearchCriteria:
    data = {
        "trip_type": "round_trip",
        "origin": "GRU",
        "destination": "MIA",
        "departure_date": "2026-12-10",
        "return_date": "2026-12-20",
        "passengers": 2,
        "travel_class": "economy",
        "currency": "BRL",
    }
    data.update(overrides)
    return SearchCriteria(**data)


def _mock_client(payload: dict) -> SerpApiClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url="https://serpapi.test", transport=transport
    )
    return SerpApiClient(http_client=http)


@pytest.fixture()
def mock_service(client):
    """Sobrescreve a dependencia do servico com transporte mockado."""
    captured: dict = {}

    class _CapturingClient(SerpApiClient):
        def search(self, params: dict) -> dict:
            captured["params"] = params
            return _fixture("serpapi_round_trip.json")

    app.dependency_overrides[get_flight_search_service] = (
        lambda: FlightSearchService(_CapturingClient())
    )
    yield captured
    app.dependency_overrides.pop(get_flight_search_service, None)


# ------------------------ build_params -------------------------

def test_build_params_round_trip():
    service = FlightSearchService(client=_mock_client({}))
    params = service.build_params(_criteria())

    assert params["type"] == 1
    assert params["departure_id"] == "GRU"
    assert params["arrival_id"] == "MIA"
    assert params["outbound_date"] == "2026-12-10"
    assert params["return_date"] == "2026-12-20"
    assert params["travel_class"] == 1
    assert params["adults"] == 2
    assert params["currency"] == "BRL"
    assert params["deep_search"] == "true"
    assert "sort_by" not in params
    assert "show_hidden" not in params
    assert params["api_key"] == "test-serpapi-key"


def test_build_params_one_way():
    service = FlightSearchService(client=_mock_client({}))
    params = service.build_params(
        _criteria(trip_type="one_way", return_date=None)
    )
    assert params["type"] == 2
    assert "return_date" not in params


def test_build_params_multi_city():
    service = FlightSearchService(client=_mock_client({}))
    criteria = _criteria(
        trip_type="multi_city",
        origin=None,
        destination=None,
        departure_date=None,
        return_date=None,
        legs=[
            {"leg_order": 1, "origin": "GRU", "destination": "LIS",
             "departure_date": "2026-12-10"},
            {"leg_order": 2, "origin": "LIS", "destination": "MAD",
             "departure_date": "2026-12-15"},
            {"leg_order": 3, "origin": "MAD", "destination": "GRU",
             "departure_date": "2026-12-22"},
        ],
    )
    params = service.build_params(criteria)
    assert params["type"] == 3
    legs = json.loads(params["multi_city_json"])
    assert legs[0] == {
        "departure_id": "GRU", "arrival_id": "LIS", "date": "2026-12-10"
    }
    assert len(legs) == 3


def test_build_params_airline_filters_and_class():
    service = FlightSearchService(client=_mock_client({}))
    params = service.build_params(
        _criteria(
            travel_class="business",
            airlines_include=["LA", "AA"],
            airlines_exclude=["G3"],
        )
    )
    assert params["travel_class"] == 3
    assert params["include_airlines"] == "LA,AA"
    assert params["exclude_airlines"] == "G3"


# ----------------------- parser / classe mista ------------------

def test_parse_detects_mixed_class_and_layover():
    service = FlightSearchService(client=_mock_client({}))
    options = service.parse_response(_fixture("serpapi_round_trip.json"), _criteria())

    # Ordenado por preco: a opcao mista (2950) vem primeiro
    assert options[0].price == 2950
    assert options[0].has_mixed_class is True
    assert options[0].mixed_class_details[0].leg_index == 2
    assert options[0].mixed_class_details[0].found_class == "business"

    # Tempo de conexao capturado
    assert options[0].stops == 1
    assert options[0].layovers[0].airport_id == "PTY"
    assert options[0].layovers[0].duration_minutes == 100
    assert options[0].total_duration_minutes == 770
    assert options[0].airlines == ["Copa Airlines"]

    # Opcoes 100% economy nao sao mistas
    assert options[1].has_mixed_class is False
    assert options[2].has_mixed_class is False


def test_parse_multi_city_three_legs():
    service = FlightSearchService(client=_mock_client({}))
    criteria = _criteria(
        trip_type="multi_city",
        origin=None, destination=None,
        departure_date=None, return_date=None,
        legs=[
            {"leg_order": 1, "origin": "GRU", "destination": "LIS",
             "departure_date": "2026-12-10"},
            {"leg_order": 2, "origin": "LIS", "destination": "MAD",
             "departure_date": "2026-12-15"},
        ],
    )
    options = service.parse_response(
        _fixture("serpapi_multi_city.json"), criteria
    )
    assert len(options[0].legs) == 3
    assert options[0].legs[2].arrival_time == "2026-12-22 20:30"
    assert options[0].airlines == ["TAP Portugal", "Iberia"]


# ------------------- endpoint: busca avulsa --------------------

def test_search_endpoint_returns_options(client, mock_service):
    resp = client.post(
        f"{API}/search",
        json={
            "trip_type": "round_trip",
            "origin": "GRU",
            "destination": "MIA",
            "departure_date": "2026-12-10",
            "return_date": "2026-12-20",
            "passengers": 2,
            "travel_class": "economy",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["option_count"] == 3
    assert body["options"][0]["price"] == "2950"
    assert body["options"][0]["has_mixed_class"] is True

    # Parametros efetivamente enviados ao provedor
    sent = mock_service["params"]
    assert sent["departure_id"] == "GRU"
    assert sent["type"] == 1


def test_search_endpoint_invalid_criteria(client):
    resp = client.post(
        f"{API}/search",
        json={"trip_type": "round_trip", "origin": "GRU", "destination": "MIA",
              "departure_date": "2026-12-10"},
    )
    assert resp.status_code == 422


# ------------- endpoint: disparo manual da rota -----------------

def test_route_manual_search_persists_result(client, family_account, mock_service):
    resp = client.post(
        f"{API}/routes",
        json={
            "family_account_id": family_account["id"],
            "trip_type": "round_trip",
            "origin": "GRU",
            "destination": "MIA",
            "departure_date": "2026-12-10",
            "return_date": "2026-12-20",
            "passengers": 2,
            "travel_class": "economy",
            "max_price": "4500.00",
        },
    )
    route_id = resp.json()["id"]

    resp = client.post(f"{API}/routes/{route_id}/search")
    assert resp.status_code == 201, resp.text
    result = resp.json()

    assert result["route_id"] == route_id
    assert result["triggered_by"] == "manual"
    assert result["lowest_price"] == "2950.00"
    assert result["has_mixed_class"] is True
    assert result["mixed_class_details"][0]["leg_index"] == 2
    assert result["layovers"][0]["airport_id"] == "PTY"
    assert len(result["legs_detail"]) == 2
    assert result["airline"] == "Copa Airlines"

    # Historico visivel no CRUD da Etapa 1
    resp = client.get(f"{API}/search-results?route_id={route_id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_route_search_not_found(client, mock_service):
    assert client.post(f"{API}/routes/99999/search").status_code == 404


# ------------------------- tratamento de erro -------------------

def test_missing_serpapi_key_returns_503(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.SERPAPI_KEY", "")
    resp = client.post(
        f"{API}/search",
        json={
            "trip_type": "one_way",
            "origin": "GRU",
            "destination": "MIA",
            "departure_date": "2026-12-10",
        },
    )
    assert resp.status_code == 503
    assert "SERPAPI_KEY" in resp.json()["detail"]


def test_serpapi_error_payload(client, family_account):
    class _ErrorClient(SerpApiClient):
        def search(self, params):
            raise SerpApiError("Erro SerpApi: limite excedido")

    app.dependency_overrides[get_flight_search_service] = (
        lambda: FlightSearchService(_ErrorClient())
    )
    try:
        resp = client.post(
            f"{API}/search",
            json={
                "trip_type": "one_way",
                "origin": "GRU",
                "destination": "MIA",
                "departure_date": "2026-12-10",
            },
        )
        assert resp.status_code == 503
        assert "limite excedido" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_flight_search_service, None)


def test_criteria_from_route_conversion(client, family_account, db):
    from app.models.monitored_route import MonitoredRoute
    from app.models.route_leg import RouteLeg

    route = MonitoredRoute(
        family_account_id=family_account["id"],
        trip_type="multi_city",
        passengers=3,
        travel_class="business",
        currency="BRL",
        airlines_include=["TP"],
    )
    route.legs.append(RouteLeg(leg_order=1, origin="GRU", destination="LIS",
                               departure_date=date(2026, 12, 10)))
    route.legs.append(RouteLeg(leg_order=2, origin="LIS", destination="MAD",
                               departure_date=date(2026, 12, 15)))
    db.add(route)
    db.commit()

    criteria = criteria_from_route(route)
    assert criteria.trip_type == "multi_city"
    assert len(criteria.legs) == 2
    assert criteria.passengers == 3
    assert criteria.travel_class == "business"
    assert criteria.airlines_include == ["TP"]
