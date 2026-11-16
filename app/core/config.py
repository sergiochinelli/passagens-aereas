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

    # SerpApi - Google Flights
    SERPAPI_BASE_URL: str = "https://serpapi.com/search.json"
    SERPAPI_TIMEOUT_SECONDS: float = 60.0
    SERPAPI_HL: str = "pt-br"
    SERPAPI_GL: str = "br"
    SERPAPI_MAX_OPTIONS: int = 500
    SERPAPI_MAX_PAGES: int = 4

    # Agendador de monitoramento (APScheduler)
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TIMEZONE: str = "UTC"
    SCHEDULER_MISFIRE_GRACE_SECONDS: int = 300
    SCHEDULER_MAX_INSTANCES: int = 1
    SCHEDULER_COALESCE: bool = True

    # Firebase Cloud Messaging — HTTP v1 com OAuth2 (conta de servico)
    # Credenciais via JSON em variavel de ambiente OU arquivo local.
    FIREBASE_CREDENTIALS_JSON: str = ""
    FIREBASE_SERVICE_ACCOUNT_FILE: str = "firebase-service-account.json"
    FIREBASE_PROJECT_ID: str = ""  # vazio = lido do JSON da conta de servico
    FCM_V1_ENDPOINT_TEMPLATE: str = (
        "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    )
    FCM_TIMEOUT_SECONDS: float = 15.0

    # CORS — origens permitidas separadas por virgula ("*" libera tudo)
    CORS_ORIGINS: str = "*"

    # Seguranca / hashing de senha
    PBKDF2_ITERATIONS: int = 260_000

    # Autenticacao da API
    # AUTH_REQUIRED=false mantem o comportamento atual (aberto) para o
    # deploy escalonado; ligar no Render quando o frontend enviar o token.
    AUTH_REQUIRED: bool = False
    AUTH_TOKEN_TTL_HOURS: int = 720  # 30 dias
    # Chave do formato legado v1 (AES-GCM). E a mesma ja publicada no bundle
    # JS do frontend — publica por natureza; serve so para verificar senhas
    # gravadas pelo app antigo. Rotacionavel via env em troca futura de app.
    AUTH_MASTER_KEY: str = (
        "18a51e94c3c25c9f68f5f3208a65c9f7a528c78239dfc6f1ceda89cadb3175e9"
    )
    AUTH_V1_SALT: str = "passagens-auth-v1"
    AUTH_V1_ITERATIONS: int = 100_000
    AUTH_USERS_SETTING_KEY: str = "auth_users"

    # Paginacao padrao das listagens
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
