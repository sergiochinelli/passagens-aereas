import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.formatting import format_brl
from app.models.device import Device
from app.models.monitored_route import MonitoredRoute
from app.models.search_result import SearchResult

logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


class FCMError(Exception):
    """Erro de envio ou configuracao do Firebase Cloud Messaging."""


@dataclass
class NotificationReport:
    """Resumo do disparo de alertas para um resultado de busca."""

    alerts_triggered: list[str] = field(default_factory=list)
    devices_targeted: int = 0
    notifications_sent: int = 0
    failures: list[dict] = field(default_factory=list)


class FCMClient:
    """Cliente FCM HTTP v1 com autenticacao OAuth2 (conta de servico).

    Credenciais resolvidas nesta ordem:
    1. settings.FIREBASE_CREDENTIALS_JSON (JSON compacto em env — producao)
    2. settings.FIREBASE_SERVICE_ACCOUNT_FILE (arquivo local — desenvolvimento)

    token_provider e project_id sao injetaveis para testes sem rede/OAuth.
    """

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        token_provider=None,
        project_id: str | None = None,
    ):
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            timeout=settings.FCM_TIMEOUT_SECONDS
        )
        self._token_provider = token_provider
        self._project_id = project_id
        self._service_account_info: dict | None = None
        self._google_credentials = None

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    # --------------------- credenciais ----------------------

    def _credentials_info(self) -> dict:
        if self._service_account_info is not None:
            return self._service_account_info
        raw = settings.FIREBASE_CREDENTIALS_JSON
        if raw:
            try:
                self._service_account_info = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise FCMError("FIREBASE_CREDENTIALS_JSON invalido") from exc
            return self._service_account_info
        path = Path(settings.FIREBASE_SERVICE_ACCOUNT_FILE)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise FCMError(
                "Credenciais Firebase nao configuradas "
                "(FIREBASE_CREDENTIALS_JSON ou arquivo de conta de servico)"
            )
        self._service_account_info = json.loads(path.read_text("utf-8"))
        return self._service_account_info

    def _resolve_project_id(self) -> str:
        if self._project_id:
            return self._project_id
        if settings.FIREBASE_PROJECT_ID:
            return settings.FIREBASE_PROJECT_ID
        return self._credentials_info()["project_id"]

    def _access_token(self) -> str:
        if self._token_provider is not None:
            return self._token_provider()
        info = self._credentials_info()
        if self._google_credentials is None:
            try:
                from google.auth.transport.requests import (
                    Request as GoogleAuthRequest,
                )
                from google.oauth2 import service_account
            except ImportError as exc:
                raise FCMError(
                    "Pacote google-auth ausente — instale requirements.txt"
                ) from exc
            self._google_credentials = (
                service_account.Credentials.from_service_account_info(
                    info, scopes=[FCM_SCOPE]
                )
            )
            self._google_auth_request = GoogleAuthRequest()
        if not self._google_credentials.valid:
            try:
                self._google_credentials.refresh(self._google_auth_request)
            except Exception as exc:
                raise FCMError(f"Falha ao obter access_token OAuth2: {exc}") from exc
        return self._google_credentials.token

    # ------------------------ envio -------------------------

    def send_push(self, token: str, title: str, body: str, data: dict) -> dict:
        endpoint = settings.FCM_V1_ENDPOINT_TEMPLATE.format(
            project_id=self._resolve_project_id()
        )
        payload = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "data": {k: str(v) for k, v in data.items() if v is not None},
            }
        }
        try:
            response = self._http.post(
                endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._access_token()}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise FCMError(f"Falha de comunicacao com FCM: {exc}") from exc
        if response.status_code != 200:
            raise FCMError(
                f"FCM retornou HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )
        return response.json()


class NotificationService:
    """Dispara push para todos os dispositivos da conta familiar.

    Regras de alerta (parametrizaveis por rota):
    - Preco: result.lowest_price <= route.max_price e alert_on_price_drop
    - Classe mista: result.has_mixed_class e alert_on_mixed_class
    """

    def __init__(self, client: FCMClient | None = None):
        self._client = client or FCMClient()

    # --------------------- regras de alerta ---------------------

    def triggered_alerts(
        self, route: MonitoredRoute, result: SearchResult
    ) -> list[str]:
        alerts = []
        if (
            route.alert_on_price_drop
            and route.max_price is not None
            and result.lowest_price is not None
            and result.lowest_price <= route.max_price
        ):
            alerts.append("price_drop")
        if route.alert_on_mixed_class and result.has_mixed_class:
            alerts.append("mixed_class")
        return alerts

    # --------------------- montagem da mensagem -----------------

    def _route_label(self, route: MonitoredRoute) -> str:
        if route.trip_type == "multi_city" and route.legs:
            return " > ".join(
                [route.legs[0].origin]
                + [leg.destination for leg in route.legs]
            )
        return f"{route.origin} > {route.destination}"

    def _build_message(
        self, alert: str, route: MonitoredRoute, result: SearchResult
    ) -> tuple[str, str]:
        label = self._route_label(route)
        price = format_brl(result.lowest_price)
        airline = result.airline or "varias companhias"
        if alert == "price_drop":
            title = f"Alerta de preco: {label}"
            body = (
                f"Menor preco: {price} ({airline}), abaixo do teto de "
                f"{format_brl(route.max_price)}."
            )
        else:
            title = f"Classe mista detectada: {label}"
            legs = [
                f"trecho {d['leg_index']} em {d.get('found_class')}"
                for d in (result.mixed_class_details or [])
            ]
            detail = ", ".join(legs) if legs else "um ou mais trechos"
            body = (
                f"Classe diferente da solicitada ({route.travel_class}): "
                f"{detail}. Preco: {price} - {airline}."
            )
        return title, body

    # ------------------------- disparo --------------------------

    def notify_result(
        self, db: Session, route: MonitoredRoute, result: SearchResult
    ) -> NotificationReport:
        report = NotificationReport()
        report.alerts_triggered = self.triggered_alerts(route, result)
        if not report.alerts_triggered:
            return report

        devices = db.scalars(
            select(Device).where(
                Device.family_account_id == route.family_account_id,
                Device.is_active.is_(True),
            )
        ).all()
        report.devices_targeted = len(devices)

        for alert in report.alerts_triggered:
            title, body = self._build_message(alert, route, result)
            data = {
                "alert_type": alert,
                "route_id": route.id,
                "result_id": result.id,
                "lowest_price": result.lowest_price,
                "currency": result.currency,
                "has_mixed_class": result.has_mixed_class,
            }
            for device in devices:
                try:
                    self._client.send_push(device.fcm_token, title, body, data)
                    report.notifications_sent += 1
                except FCMError as exc:
                    logger.warning(
                        "Push falhou p/ device %s (%s): %s",
                        device.id, device.label, exc,
                    )
                    report.failures.append(
                        {"device_id": device.id, "alert": alert, "error": str(exc)}
                    )
        logger.info(
            "Alertas rota %s: %s | enviados %s/%s",
            route.id, report.alerts_triggered,
            report.notifications_sent, report.devices_targeted,
        )
        return report

    def send_test_push(
        self, db: Session, device_id: int, title: str, body: str
    ) -> dict:
        device = db.get(Device, device_id)
        if device is None:
            raise FCMError(f"Dispositivo {device_id} nao encontrado")
        return self._client.send_push(
            device.fcm_token, title, body, {"alert_type": "test"}
        )
