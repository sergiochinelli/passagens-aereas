from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Todas as configuracoes vem do ambiente / arquivo .env.

    Nenhum valor sensivel ou de infraestrutura fica fixo no codigo.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Aplicacao
    APP_NAME: str = "Passagens Aereas API"
    APP_VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # Banco de dados (PostgreSQL em producao; ex.: sqlite:///./test.db para testes)
    DATABASE_URL: str = "postgresql+psycopg2://postgres:CHANGE_ME@localhost:5432/passagens_aereas"
    DB_ECHO: bool = False

    # Integracoes (preenchidas via .env ou painel - nunca no codigo)
    SERPAPI_KEY: str = ""
    FCM_KEY: str = ""

    # SerpApi - Google Flights
    SERPAPI_BASE_URL: str = "https://serpapi.com/search.json"
    SERPAPI_TIMEOUT_SECONDS: float = 30.0
    SERPAPI_HL: str = "pt-br"
    SERPAPI_GL: str = "br"
    SERPAPI_MAX_OPTIONS: int = 10

    # Agendador de monitoramento (APScheduler)
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TIMEZONE: str = "UTC"
    SCHEDULER_MISFIRE_GRACE_SECONDS: int = 300
    SCHEDULER_MAX_INSTANCES: int = 1
    SCHEDULER_COALESCE: bool = True

    # Firebase Cloud Messaging (legacy HTTP API — chave via .env)
    FCM_ENDPOINT: str = "https://fcm.googleapis.com/fcm/send"
    FCM_TIMEOUT_SECONDS: float = 15.0

    # CORS — origens permitidas separadas por virgula ("*" libera tudo)
    CORS_ORIGINS: str = "*"

    # Seguranca / hashing de senha
    PBKDF2_ITERATIONS: int = 260_000

    # Paginacao padrao das listagens
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
