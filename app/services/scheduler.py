import logging

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.monitored_route import MonitoredRoute
from app.services.flight_search import FlightSearchService
from app.services.serpapi_client import SerpApiError

logger = logging.getLogger(__name__)

_JOB_PREFIX = "route_monitor_"


def job_id_for(route_id: int) -> str:
    return f"{_JOB_PREFIX}{route_id}"


def run_route_check(route_id: int, session_factory=None) -> None:
    """Executa uma verificacao agendada de preco para a rota.

    Abre sessao propria (roda em thread do scheduler), respeita o flag
    is_active e registra o resultado em search_results.
    """
    factory = session_factory or SessionLocal
    db: Session = factory()
    try:
        route = db.scalar(
            select(MonitoredRoute)
            .options(selectinload(MonitoredRoute.legs))
            .where(MonitoredRoute.id == route_id)
        )
        if route is None or not route.is_active:
            logger.info("Rota %s inexistente/inativa — removendo job", route_id)
            get_route_scheduler().unschedule_route(route_id)
            return
        FlightSearchService().search_route(db, route, triggered_by="scheduled")
        logger.info("Monitoramento agendado executado para rota %s", route_id)
    except SerpApiError as exc:
        logger.warning("SerpApi falhou no monitor da rota %s: %s", route_id, exc)
    except Exception:
        logger.exception("Falha inesperada no monitor da rota %s", route_id)
    finally:
        db.close()


class RouteScheduler:
    """Gerencia jobs APScheduler espelhando as rotas monitoradas ativas.

    - Um job por rota: IntervalTrigger(minutes=route.monitor_interval_minutes)
    - O banco e a fonte da verdade: no startup as rotas ativas sao
      carregadas e agendadas (persistencia via DB, nao via jobstore)
    - sync_route() e chamado pelo CRUD de rotas para manter jobs em dia
    """

    def __init__(self, scheduler: BackgroundScheduler | None = None):
        self._scheduler = scheduler or BackgroundScheduler(
            timezone=settings.SCHEDULER_TIMEZONE,
            job_defaults={
                "coalesce": settings.SCHEDULER_COALESCE,
                "max_instances": settings.SCHEDULER_MAX_INSTANCES,
                "misfire_grace_time": settings.SCHEDULER_MISFIRE_GRACE_SECONDS,
            },
        )

    # --------------------- ciclo de vida ---------------------

    @property
    def running(self) -> bool:
        return self._scheduler.running

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self, wait: bool = False) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)

    # --------------------- sincronizacao ---------------------

    def schedule_route(self, route: MonitoredRoute) -> None:
        """(Re)agenda o job da rota conforme seus parametros atuais.

        Remove o job anterior antes de readicionar: com o scheduler parado
        os jobs ficam pendentes e replace_existing nao atualiza o trigger.
        """
        self.unschedule_route(route.id)
        self._scheduler.add_job(
            run_route_check,
            trigger=IntervalTrigger(minutes=route.monitor_interval_minutes),
            id=job_id_for(route.id),
            args=[route.id],
            name=f"monitor route {route.id}",
            replace_existing=True,
        )

    def unschedule_route(self, route_id: int) -> None:
        try:
            self._scheduler.remove_job(job_id_for(route_id))
        except JobLookupError:
            pass

    def sync_route(self, route: MonitoredRoute) -> None:
        """Mantem o job alinhado ao estado da rota (ativa/inativa)."""
        if route.is_active:
            self.schedule_route(route)
        else:
            self.unschedule_route(route.id)

    def load_active_routes(self, db: Session | None = None) -> int:
        """Carrega todas as rotas ativas do banco e agenda seus jobs."""
        owns_session = db is None
        session = db or SessionLocal()
        try:
            routes = session.scalars(
                select(MonitoredRoute).where(MonitoredRoute.is_active.is_(True))
            ).all()
            for route in routes:
                self.schedule_route(route)
            logger.info("Scheduler: %d rota(s) ativa(s) agendada(s)", len(routes))
            return len(routes)
        finally:
            if owns_session:
                session.close()

    # --------------------- consulta ---------------------

    def get_job(self, route_id: int):
        return self._scheduler.get_job(job_id_for(route_id))

    def list_jobs(self) -> list[dict]:
        jobs = []
        for job in self._scheduler.get_jobs():
            route_id = int(job.id.replace(_JOB_PREFIX, ""))
            jobs.append(
                {
                    "job_id": job.id,
                    "route_id": route_id,
                    "name": job.name,
                    "trigger": str(job.trigger),
                    "next_run_time": (
                        job.next_run_time.isoformat()
                        if getattr(job, "next_run_time", None)
                        else None
                    ),
                }
            )
        return jobs


_route_scheduler: RouteScheduler | None = None


def get_route_scheduler() -> RouteScheduler:
    global _route_scheduler
    if _route_scheduler is None:
        _route_scheduler = RouteScheduler()
    return _route_scheduler


def reset_route_scheduler() -> None:
    """Substitui o singleton (uso exclusivo em testes)."""
    global _route_scheduler
    _route_scheduler = None
