import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.services.scheduler import get_route_scheduler

# Importa todos os modelos para registrar as tabelas no metadata
import app.models  # noqa: F401

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cria as tabelas no startup (provisorio ate a introducao de migrations)
    Base.metadata.create_all(bind=engine)

    scheduler = get_route_scheduler()
    if settings.SCHEDULER_ENABLED:
        scheduler.start()
        try:
            scheduler.load_active_routes()
        except Exception:
            logger.exception("Scheduler: falha ao carregar rotas ativas")

    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


app.include_router(api_router, prefix=settings.API_V1_PREFIX)
