import re
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.db.session import get_db
from app.models.auth_session import AuthSession
from app.services.auth_service import get_valid_session
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


# ---------------------------------------------------------------------------
# Autenticacao
#
# Rotas publicas mesmo com AUTH_REQUIRED=true: necessarias ao fluxo de login
# do frontend (selecionar a conta, listar usuarios, criar conta nova).
# ---------------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)

_PUBLIC_EXACT = {
    ("GET", "/api/v1/family-accounts"),
    ("POST", "/api/v1/family-accounts"),
}
_PUBLIC_GET_PATTERN = re.compile(r"^/api/v1/family-accounts/\d+$")


def _is_public_route(request: Request) -> bool:
    path = request.url.path.rstrip("/") or "/"
    if (request.method, path) in _PUBLIC_EXACT:
        return True
    return request.method == "GET" and bool(_PUBLIC_GET_PATTERN.match(path))


def get_current_session(
    db: DbSession,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
) -> AuthSession:
    token = credentials.credentials if credentials else None
    session = get_valid_session(db, token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessao invalida ou expirada",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return session


def require_auth(
    request: Request,
    db: DbSession,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
) -> AuthSession | None:
    """Guarda global: valida o token quando AUTH_REQUIRED esta ligado."""
    if not app_settings.AUTH_REQUIRED or _is_public_route(request):
        return None
    return get_current_session(db, credentials)


CurrentSession = Annotated[AuthSession, Depends(get_current_session)]
RequireAuth = Annotated[AuthSession | None, Depends(require_auth)]
