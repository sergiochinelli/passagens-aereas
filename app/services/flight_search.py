import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.monitored_route import MonitoredRoute
from app.models.search_result import SearchResult
from app.schemas.flight_search import (
    FlightOption,
    FlightSearchResponse,
    LayoverDetail,
    LegDetail,
    MixedClassDetail,
    SearchCriteria,
)
from app.services.notification import NotificationService
from app.services.serpapi_client import SerpApiClient

logger = logging.getLogger(__name__)

# Mapeamentos entre os valores internos e os codigos da SerpApi
_TRIP_TYPE_TO_SERPAPI = {"round_trip": 1, "one_way": 2, "multi_city": 3}
_TRAVEL_CLASS_TO_SERPAPI = {
    "economy": 1,
    "premium_economy": 2,
    "business": 3,
    "first": 4,
}


def _normalize_class(value: str | None) -> str | None:
    """Normaliza o texto de classe retornado pela SerpApi p/ o padrao interno."""
    if value is None:
        return None
    return value.strip().lower().replace(" ", "_")


class FlightSearchService:
    """Busca de voos no Google Flights via SerpApi.

    Responsabilidades:
    - Traduzir SearchCriteria (ou MonitoredRoute) para os parametros da API
    - Normalizar cada opcao de voo retornada
    - Detectar classe mista comparando a classe solicitada com a de cada trecho
    - Persistir a melhor opcao em search_results quando a busca e de rota
    """

    def __init__(
        self,
        client: SerpApiClient | None = None,
        notifier: NotificationService | None = None,
    ):
        self._client = client or SerpApiClient()
        self._notifier = notifier or NotificationService()

    # ------------------------- parametros -------------------------

    def build_params(self, criteria: SearchCriteria) -> dict:
        params: dict = {
            "type": _TRIP_TYPE_TO_SERPAPI[criteria.trip_type],
            "travel_class": _TRAVEL_CLASS_TO_SERPAPI[criteria.travel_class],
            "adults": criteria.passengers,
            "currency": criteria.currency,
            "hl": settings.SERPAPI_HL,
            "gl": settings.SERPAPI_GL,
            "deep_search": "true",
            "api_key": settings.SERPAPI_KEY,
        }

        if criteria.trip_type == "multi_city":
            params["multi_city_json"] = json.dumps(
                [
                    {
                        "departure_id": leg.origin,
                        "arrival_id": leg.destination,
                        "date": leg.departure_date.isoformat(),
                    }
                    for leg in criteria.legs
                ]
            )
        else:
            params["departure_id"] = criteria.origin
            params["arrival_id"] = criteria.destination
            params["outbound_date"] = criteria.departure_date.isoformat()
            if criteria.trip_type == "round_trip":
                params["return_date"] = criteria.return_date.isoformat()

        if criteria.airlines_include:
            params["include_airlines"] = ",".join(criteria.airlines_include)
        if criteria.airlines_exclude:
            params["exclude_airlines"] = ",".join(criteria.airlines_exclude)

        return params

    # --------------------------- parser ---------------------------

    def parse_option(
        self, group: dict, requested_class: str, currency: str
    ) -> FlightOption:
        legs: list[LegDetail] = []
        airlines: list[str] = []
        mixed: list[MixedClassDetail] = []

        for index, leg in enumerate(group.get("flights", []), start=1):
            found_class = _normalize_class(leg.get("travel_class"))
            if found_class is not None and found_class != requested_class:
                mixed.append(
                    MixedClassDetail(
                        leg_index=index,
                        expected_class=requested_class,
                        found_class=found_class,
                    )
                )
            airline_name = leg.get("airline")
            if airline_name and airline_name not in airlines:
                airlines.append(airline_name)
            legs.append(
                LegDetail(
                    leg_index=index,
                    origin=(leg.get("departure_airport") or {}).get("id"),
                    origin_name=(leg.get("departure_airport") or {}).get("name"),
                    destination=(leg.get("arrival_airport") or {}).get("id"),
                    destination_name=(leg.get("arrival_airport") or {}).get("name"),
                    departure_time=(leg.get("departure_airport") or {}).get("time"),
                    arrival_time=(leg.get("arrival_airport") or {}).get("time"),
                    airline=airline_name,
                    flight_number=leg.get("flight_number"),
                    travel_class=found_class,
                    duration_minutes=leg.get("duration"),
                    overnight=bool(leg.get("overnight", False)),
                )
            )

        layovers = [
            LayoverDetail(
                airport_id=lay.get("id"),
                name=lay.get("name"),
                duration_minutes=lay.get("duration"),
                overnight=bool(lay.get("overnight", False)),
            )
            for lay in group.get("layovers", [])
        ]

        price = group.get("price")
        return FlightOption(
            price=price,
            currency=currency,
            airlines=airlines,
            total_duration_minutes=group.get("total_duration"),
            stops=len(layovers),
            layovers=layovers,
            legs=legs,
            has_mixed_class=bool(mixed),
            mixed_class_details=mixed,
            booking_token=group.get("booking_token"),
        )

    def parse_response(
        self, payload: dict, criteria: SearchCriteria
    ) -> list[FlightOption]:
        groups = (payload.get("best_flights") or []) + (
            payload.get("other_flights") or []
        )
        options = [
            self.parse_option(group, criteria.travel_class, criteria.currency)
            for group in groups
        ]
        options.sort(
            key=lambda opt: opt.price if opt.price is not None else float("inf")
        )
        return options[: settings.SERPAPI_MAX_OPTIONS]

    def _option_signature(self, opt: FlightOption) -> tuple:
        return (
            opt.price,
            tuple(opt.airlines),
            tuple(
                (leg.origin, leg.destination, leg.departure_time, leg.arrival_time)
                for leg in opt.legs
            ),
        )

    def _collect_groups(self, payload: dict, seen: set) -> list:
        """Extrai grupos de voo ineditos de uma pagina de resposta."""
        groups = []
        for group in (payload.get("best_flights") or []) + (
            payload.get("other_flights") or []
        ):
            flights = group.get("flights") or []
            sig = (
                group.get("booking_token"),
                group.get("price"),
                tuple(
                    (
                        (f.get("departure_airport") or {}).get("id"),
                        (f.get("arrival_airport") or {}).get("id"),
                        (f.get("departure_airport") or {}).get("time"),
                    )
                    for f in flights
                ),
            )
            if sig in seen:
                continue
            seen.add(sig)
            groups.append(group)
        return groups

    def _fetch_all_groups(self, params: dict, max_pages: int) -> list:
        """Busca avulsa: percorre as paginas da SerpApi ate esgotar o resultado.

        Cada pagina consome 1 credito SerpApi — por isso so e usada na busca
        avulsa; o monitoramento de rotas continua com uma unica pagina.
        """
        seen: set = set()
        groups: list = []
        page_params = dict(params)
        for _ in range(max(1, max_pages)):
            payload = self._client.search(page_params)
            groups.extend(self._collect_groups(payload, seen))
            pagination = payload.get("serpapi_pagination") or {}
            token = pagination.get("next_page_token")
            if not token:
                break
            page_params = {**params, "next_page_token": token}
        return groups

    # --------------------------- buscas ---------------------------

    def _options_from_groups(
        self, groups: list, criteria: SearchCriteria
    ) -> list[FlightOption]:
        options = [
            self.parse_option(group, criteria.travel_class, criteria.currency)
            for group in groups
        ]
        options.sort(
            key=lambda opt: opt.price if opt.price is not None else float("inf")
        )
        return options[: settings.SERPAPI_MAX_OPTIONS]

    def search(self, criteria: SearchCriteria) -> FlightSearchResponse:
        """Busca avulsa: retorna TODAS as opcoes da fonte, sem persistir."""
        params = self.build_params(criteria)
        groups = self._fetch_all_groups(params, settings.SERPAPI_MAX_PAGES)
        options = self._options_from_groups(groups, criteria)
        return FlightSearchResponse(
            searched_at=datetime.now(timezone.utc),
            criteria=criteria,
            options=options,
            option_count=len(options),
        )

    def search_route(
        self, db: Session, route: MonitoredRoute, triggered_by: str = "manual"
    ) -> SearchResult:
        """Busca de rota monitorada: persiste a melhor opcao em search_results."""
        criteria = criteria_from_route(route)
        params = self.build_params(criteria)
        payload = self._client.search(params)
        options = self.parse_response(payload, criteria)

        best = options[0] if options else None
        result = SearchResult(
            route_id=route.id,
            triggered_by=triggered_by,
            lowest_price=best.price if best else None,
            currency=criteria.currency,
            airline=", ".join(best.airlines) if best else None,
            total_duration_minutes=best.total_duration_minutes if best else None,
            stops=best.stops if best else None,
            layovers=[lay.model_dump() for lay in best.layovers] if best else [],
            legs_detail=[leg.model_dump() for leg in best.legs] if best else [],
            has_mixed_class=best.has_mixed_class if best else False,
            mixed_class_details=(
                [m.model_dump() for m in best.mixed_class_details] if best else []
            ),
            raw_payload=payload,
        )
        db.add(result)
        route.last_checked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(result)

        # Alertas push: falhas de notificacao nunca afetam a busca persistida
        try:
            self._notifier.notify_result(db, route, result)
        except Exception:
            logger.exception(
                "Falha ao disparar notificacoes da rota %s", route.id
            )
        return result


def criteria_from_route(route: MonitoredRoute) -> SearchCriteria:
    """Converte uma rota monitorada persistida em SearchCriteria."""
    return SearchCriteria(
        trip_type=route.trip_type,
        origin=route.origin,
        destination=route.destination,
        departure_date=route.departure_date,
        return_date=route.return_date,
        passengers=route.passengers,
        travel_class=route.travel_class,
        currency=route.currency,
        airlines_include=route.airlines_include,
        airlines_exclude=route.airlines_exclude,
        legs=[
            {
                "leg_order": leg.leg_order,
                "origin": leg.origin,
                "destination": leg.destination,
                "departure_date": leg.departure_date,
            }
            for leg in route.legs
        ],
    )
