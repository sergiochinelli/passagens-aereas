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
    """Normaliza o texto de classe retornado pela SerpApi p/ o padrao interno.

    A fonte escreve "Business Class"/"Economy"/"Premium Economy" — removemos
    o sufixo " Class" para comparar com a classe solicitada (business etc.).
    """
    if value is None:
        return None
    norm = value.strip().lower().replace(" ", "_")
    return norm.removesuffix("_class")


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
            departure_token=group.get("departure_token"),
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

    def _fetch_all_groups(self, params: dict, max_pages: int) -> tuple[list, str | None]:
        """Busca avulsa: percorre as paginas da SerpApi ate esgotar o resultado.

        Cada pagina consome 1 credito SerpApi — por isso so e usada na busca
        avulsa; o monitoramento de rotas continua com uma unica pagina.
        Retorna (grupos, url do Google Flights da 1a pagina).
        """
        seen: set = set()
        groups: list = []
        search_url: str | None = None
        page_params = dict(params)
        for _ in range(max(1, max_pages)):
            payload = self._client.search(page_params)
            if search_url is None:
                search_url = (payload.get("search_metadata") or {}).get(
                    "google_flights_url"
                )
            groups.extend(self._collect_groups(payload, seen))
            pagination = payload.get("serpapi_pagination") or {}
            token = pagination.get("next_page_token")
            if not token:
                break
            page_params = {**params, "next_page_token": token}
        return groups, search_url

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
        groups, search_url = self._fetch_all_groups(
            params, settings.SERPAPI_MAX_PAGES
        )
        options = self._options_from_groups(groups, criteria)
        return FlightSearchResponse(
            searched_at=datetime.now(timezone.utc),
            criteria=criteria,
            options=options,
            option_count=len(options),
            search_url=search_url,
        )

    def booking_options(
        self,
        criteria: SearchCriteria,
        departure_token: str | None = None,
        booking_token: str | None = None,
    ) -> list:
        """Resolve os vendedores (cia/agencia) de uma opcao ja exibida.

        Ida e volta: 1a chamada com departure_token devolve as voltas
        possiveis; a mais barata com booking_token segue para a 2a
        chamada, que traz os canais de venda com link de compra.
        """
        params = self.build_params(criteria)
        # tokens de continuacao ja carregam o contexto da busca profunda
        # original; reenviar deep_search so adiciona latencia
        params.pop("deep_search", None)
        token = booking_token
        return_option = None
        if token is None and departure_token:
            payload = self._client.search(
                {**params, "departure_token": departure_token}
            )
            returns = (payload.get("best_flights") or []) + (
                payload.get("other_flights") or []
            )
            with_token = [g for g in returns if g.get("booking_token")]
            with_token.sort(key=lambda g: g.get("price") or float("inf"))
            if with_token:
                token = with_token[0]["booking_token"]
                # a volta escolhida (mais barata) tambem vai na resposta —
                # o Google so exibe a ida nos resultados de ida-e-volta
                return_option = self.parse_option(
                    with_token[0], criteria.travel_class, criteria.currency
                )
        if token is None:
            return {"options": [], "return_option": None}

        payload = self._client.search({**params, "booking_token": token})
        options = []
        for entry in payload.get("booking_options") or []:
            for kind, combined in (("together", True), ("separately", False)):
                seller = entry.get(kind)
                if not seller:
                    continue
                req = seller.get("booking_request") or {}
                options.append(
                    {
                        "book_with": seller.get("book_with"),
                        "price": seller.get("price"),
                        "currency": criteria.currency,
                        "url": req.get("url"),
                        "post_data": req.get("post_data"),
                        "together": combined,
                        "airline": bool(seller.get("airline")),
                        "marketed_as": seller.get("marketed_as") or [],
                        "baggage_prices": seller.get("baggage_prices") or [],
                    }
                )
        # bilhetes unicos primeiro; separados por ultimo
        options.sort(key=lambda o: (not o["together"], o["price"] or 0))
        return {"options": options, "return_option": return_option}

    def search_route(
        self, db: Session, route: MonitoredRoute, triggered_by: str = "manual"
    ) -> SearchResult:
        """Busca de rota monitorada: persiste a melhor opcao em search_results."""
        criteria = criteria_from_route(route)
        params = self.build_params(criteria)
        payload = self._client.search(params)
        options = self.parse_response(payload, criteria)

        best = options[0] if options else None
        # SerpApi devolve o TOTAL da viagem; padrao interno e POR PESSOA
        # (mesma unidade do max_price e da convencao dos sites de viagem)
        lowest_per_person = (
            round(best.price / (criteria.passengers or 1), 2) if best else None
        )
        result = SearchResult(
            route_id=route.id,
            triggered_by=triggered_by,
            lowest_price=lowest_per_person,
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
