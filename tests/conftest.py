import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Banco de teste: SQLite em memoria por padrao (o SQLAlchemy abstrai o
# dialeto). Para validar contra PostgreSQL real, exportar TEST_DATABASE_URL
# antes de rodar o pytest. Em producao o DATABASE_URL vem do .env.
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite://")
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["SERPAPI_KEY"] = "test-serpapi-key"
os.environ["FIREBASE_CREDENTIALS_JSON"] = (
    '{"project_id": "test-project", "client_email": "test@example.com"}'
)
os.environ["SCHEDULER_ENABLED"] = "false"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402,F401  (importa antes de 'from app.main import app')
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402  instancia FastAPI (nome nao pode ser sombreado)


@pytest.fixture(scope="session")
def engine():
    if TEST_DB_URL.startswith("sqlite"):
        return create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(TEST_DB_URL)


@pytest.fixture(scope="session")
def session_factory(engine):
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(db, session_factory):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def family_account(client):
    resp = client.post(
        "/api/v1/family-accounts", json={"name": "Familia Costa"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()
