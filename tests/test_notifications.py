"""Testes funcionais da Etapa 4 - Sistema de alertas via FCM.

A camada HTTP do FCM e substituida por cliente falso / MockTransport:
nenhuma chamada real e feita. Conteudo das mensagens e regras de alerta
sao verificados integralmente.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.api.deps import get_flight_search_service, get_notification_service
from app.core.formatting import format_brl
from app.main import app
from app.models.device import Device
from app.models.monitored_route import MonitoredRoute
from app.models.search_result import SearchResult
from app.services.flight_search import FlightSearchService
from app.services.notification import (
    FCMClient,
    FCMError,
    NotificationService,
)
from app.services.serpapi_client import SerpApiClient

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures"


class _FakeFCM(FCMClient):
    """Captura os pushes enviados sem fazer chamada HTTP."""

    def __init__(self, fail_for: set[str] | None = None):
        self.sent: list[dict] = []
        self._fail_for = fail_for or set()

    def send_push(self, token, title, body, data):
        if token in self._fail_for:
            raise FCMError("NotRegistered")
        self.sent.append({"token": token, "title": title, "body": body,
                          "data": data})
        return {"message_id": f"msg-{len(self.sent)}"}


class _FakeSerpApi(SerpApiClient):
    def __init__(self, fixture: str):
        self._fixture = fixture

    def search(self, params):
        return json.loads((FIXTURES / self._fixture).read_text("utf-8"))


def _route(db, family_id, **overrides) -> MonitoredRoute:
    data = {
        "family_account_id": family_id,
        "trip_type": "round_trip",
        "origin": "GRU",
        "destination": "MIA",
        "departure_date": date(2026, 12, 10),
        "return_date": date(2026, 12, 20),
        "passengers": 2,
        "travel_class": "economy",
        "max_price": Decimal("4500.00"),
        "currency": "BRL",
        "alert_on_price_drop": True,
        "alert_on_mixed_class": True,
        "is_active": True,
    }
    data.update(overrides)
    route = MonitoredRoute(**data)
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


def _device(db, family_id, token, platform="android", active=True):
    device = Device(
        family_account_id=family_id, platform=platform,
        fcm_token=token, label=f"{platform}-{token}", is_active=active,
    )
    db.add(device)
    db.commit()
    return device


def _result(route_id, price="2950.00", mixed=True) -> SearchResult:
    return SearchResult(
        route_id=route_id,
        triggered_by="scheduled",
        lowest_price=Decimal(price),
        currency="BRL",
        airline="Copa Airlines",
        total_duration_minutes=770,
        stops=1,
        layovers=[{"airport_id": "PTY", "duration_minutes": 100}],
        legs_detail=[{"leg_index": 1}, {"leg_index": 2}],
        has_mixed_class=mixed,
        mixed_class_details=(
            [{"leg_index": 2, "expected_class": "economy",
              "found_class": "business"}] if mixed else []
        ),
    )


# ------------------------- formatacao -------------------------

def test_format_brl():
    assert format_brl(Decimal("2950.00")) == "R$ 2.950,00"
    assert format_brl(1234567.89) == "R$ 1.234.567,89"
    assert format_brl(Decimal("45")) == "R$ 45,00"
    assert format_brl(None) == "R$ -"


# ---------------------- regras de alerta -----------------------

def test_triggered_alerts_price_and_mixed(db, family_account):
    route = _route(db, family_account["id"])
    result = _result(route.id)

    service = NotificationService(_FakeFCM())
    alerts = service.triggered_alerts(route, result)
    assert set(alerts) == {"price_drop", "mixed_class"}


def test_triggered_alerts_price_above_max_no_alert(db, family_account):
    route = _route(db, family_account["id"], max_price=Decimal("2000.00"))
    result = _result(route.id, price="2950.00", mixed=False)

    service = NotificationService(_FakeFCM())
    assert service.triggered_alerts(route, result) == []


def test_triggered_alerts_flags_disable(db, family_account):
    route = _route(
        db, family_account["id"],
        alert_on_price_drop=False, alert_on_mixed_class=False,
    )
    result = _result(route.id)

    service = NotificationService(_FakeFCM())
    assert service.triggered_alerts(route, result) == []


# ------------------------- disparo push ------------------------

def test_notify_all_family_devices(db, family_account):
    fid = family_account["id"]
    route = _route(db, fid)
    result = _result(route.id)
    db.add(result)
    db.commit()
    _device(db, fid, "token-all-android", "android")
    _device(db, fid, "token-all-web", "web")
    _device(db, fid, "token-all-inativo", "android", active=False)

    fcm = _FakeFCM()
    report = NotificationService(fcm).notify_result(db, route, result)

    # 2 alertas x 2 dispositivos ativos = 4 pushes
    assert report.devices_targeted == 2
    assert report.notifications_sent == 4
    tokens = {s["token"] for s in fcm.sent}
    assert tokens == {"token-all-android", "token-all-web"}

    # Conteudo do alerta de preco
    price_msgs = [s for s in fcm.sent if s["data"]["alert_type"] == "price_drop"]
    assert "R$ 2.950,00" in price_msgs[0]["body"]
    assert "R$ 4.500,00" in price_msgs[0]["body"]
    assert "Copa Airlines" in price_msgs[0]["body"]
    assert "GRU" in price_msgs[0]["title"]

    # Conteudo do alerta de classe mista
    mixed_msgs = [s for s in fcm.sent if s["data"]["alert_type"] == "mixed_class"]
    assert "trecho 2" in mixed_msgs[0]["body"]
    assert "business" in mixed_msgs[0]["body"]


def test_notify_no_devices_no_crash(db, family_account):
    route = _route(db, family_account["id"])
    result = _result(route.id)
    db.add(result)
    db.commit()

    report = NotificationService(_FakeFCM()).notify_result(db, route, result)
    assert report.notifications_sent == 0
    assert report.devices_targeted == 0


def test_notify_fcm_failure_collected(db, family_account):
    fid = family_account["id"]
    route = _route(db, fid)
    result = _result(route.id)
    db.add(result)
    db.commit()
    _device(db, fid, "token-fail-ok", "android")
    _device(db, fid, "token-fail-morto", "android")

    fcm = _FakeFCM(fail_for={"token-fail-morto"})
    report = NotificationService(fcm).notify_result(db, route, result)

    assert report.notifications_sent == 2  # 2 alertas, so 1 device ok
    assert len(report.failures) == 2
    assert all(f["error"] == "NotRegistered" for f in report.failures)


def test_notify_no_alert_no_send(db, family_account):
    route = _route(db, family_account["id"], max_price=Decimal("1000.00"))
    result = _result(route.id, price="5000.00", mixed=False)
    db.add(result)
    db.commit()
    _device(db, family_account["id"], "token-noalert")

    fcm = _FakeFCM()
    report = NotificationService(fcm).notify_result(db, route, result)
    assert report.alerts_triggered == []
    assert fcm.sent == []


# ------------------- integracao search_route -------------------

def test_search_route_triggers_notifications(db, family_account):
    fid = family_account["id"]
    route = _route(db, fid)
    _device(db, fid, "token-int-android")
    _device(db, fid, "token-int-web")

    fcm = _FakeFCM()
    service = FlightSearchService(
        client=_FakeSerpApi("serpapi_round_trip.json"),
        notifier=NotificationService(fcm),
    )
    result = service.search_route(db, route, triggered_by="scheduled")

    # Fixture: menor preco 2950 <= teto 4500 e classe mista no trecho 2
    assert result.has_mixed_class is True
    assert len(fcm.sent) == 4  # 2 alertas x 2 devices
    assert {s["data"]["alert_type"] for s in fcm.sent} == {
        "price_drop", "mixed_class"
    }


def test_search_route_no_alert_when_above_max(db, family_account):
    route = _route(
        db, family_account["id"],
        max_price=Decimal("1000.00"), alert_on_mixed_class=False,
    )
    fcm = _FakeFCM()
    service = FlightSearchService(
        client=_FakeSerpApi("serpapi_round_trip.json"),
        notifier=NotificationService(fcm),
    )
    service.search_route(db, route, triggered_by="manual")
    assert fcm.sent == []


def test_notification_failure_does_not_break_search(db, family_account):
    route = _route(db, family_account["id"])
    _device(db, family_account["id"], "token-exploding")

    class _ExplodingNotifier(NotificationService):
        def notify_result(self, *a, **kw):
            raise RuntimeError("FCM fora do ar")

    service = FlightSearchService(
        client=_FakeSerpApi("serpapi_round_trip.json"),
        notifier=_ExplodingNotifier(),
    )
    result = service.search_route(db, route, triggered_by="manual")
    assert result.id is not None  # resultado persistido mesmo assim


# ----------------------- FCMClient (HTTP) -----------------------

def test_fcm_client_payload_and_headers():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"message_id": "ok-1"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = FCMClient(http_client=http)

    resp = client.send_push("tok-abc", "Titulo", "Corpo", {"k": "v"})
    assert resp == {"message_id": "ok-1"}
    assert captured["headers"]["authorization"] == "key=test-fcm-key"
    assert captured["json"]["to"] == "tok-abc"
    assert captured["json"]["notification"]["title"] == "Titulo"
    assert captured["json"]["data"] == {"k": "v"}


def test_fcm_client_missing_key(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FCM_KEY", "")
    client = FCMClient()
    with pytest.raises(FCMError, match="FCM_KEY"):
        client.send_push("tok", "t", "b", {})


# --------------------- endpoint de teste push ------------------

def test_test_push_endpoint(client, db, family_account):
    device = _device(db, family_account["id"], "token-testpush")
    fcm = _FakeFCM()
    notifier = NotificationService(fcm)
    app.dependency_overrides[get_notification_service] = lambda: notifier
    try:
        resp = client.post(
            f"{API}/notifications/test",
            json={"device_id": device.id, "title": "Teste", "body": "Corpo"},
        )
        assert resp.status_code == 200
        assert fcm.sent[0]["token"] == "token-testpush"
    finally:
        app.dependency_overrides.pop(get_notification_service, None)


def test_test_push_device_not_found(client):
    notifier = NotificationService(_FakeFCM())
    app.dependency_overrides[get_notification_service] = lambda: notifier
    try:
        resp = client.post(
            f"{API}/notifications/test",
            json={"device_id": 99999, "title": "T", "body": "B"},
        )
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.pop(get_notification_service, None)
