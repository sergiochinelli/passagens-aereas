import httpx

from app.core.config import settings


class SerpApiError(Exception):
    """Erro de comunicacao ou resposta da SerpApi."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SerpApiClient:
    """Cliente HTTP minimo para a SerpApi (engine google_flights).

    A chave vem exclusivamente de settings.SERPAPI_KEY (.env).
    O transporte HTTP e injetavel para permitir testes sem rede.
    """

    def __init__(self, http_client: httpx.Client | None = None):
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=settings.SERPAPI_BASE_URL,
            timeout=settings.SERPAPI_TIMEOUT_SECONDS,
        )

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def search(self, params: dict) -> dict:
        if not settings.SERPAPI_KEY:
            raise SerpApiError("SERPAPI_KEY nao configurada no .env")

        request_params = {"engine": "google_flights", **params}
        try:
            response = self._http.get("", params=request_params)
        except httpx.HTTPError as exc:
            raise SerpApiError(f"Falha de comunicacao com SerpApi: {exc}") from exc

        if response.status_code != 200:
            raise SerpApiError(
                f"SerpApi retornou HTTP {response.status_code}",
                status_code=response.status_code,
            )

        payload = response.json()
        if "error" in payload:
            raise SerpApiError(f"Erro SerpApi: {payload['error']}")
        return payload
