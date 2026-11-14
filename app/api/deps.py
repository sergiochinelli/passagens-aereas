from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.flight_search import FlightSearchService
from app.services.notification import FCMClient, NotificationService
from app.services.serpapi_client import SerpApiClient

DbSession = Annotated[Session, Depends(get_db)]


def get_flight_search_service() -> FlightSearchService:
    """Constroi o servico de busca por requisicao (transporte injetavel)."""
    return FlightSearchService(SerpApiClient())


FlightService = Annotated[FlightSearchService, Depends(get_flight_search_service)]


def get_notification_service() -> NotificationService:
    return NotificationService(FCMClient())


Notifier = Annotated[NotificationService, Depends(get_notification_service)]
