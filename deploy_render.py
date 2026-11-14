"""Deploy automatico do backend no Render via API oficial.

Uso:
    set RENDER_API_KEY=rnd_...
    python deploy_render.py

O script:
1. Autentica na API do Render com RENDER_API_KEY (variavel de ambiente).
2. Cria (ou reutiliza) um Web Service apontando para o repo GitHub.
   O repo pode ser sobrescrito via RENDER_REPO_URL.
3. Configura build/start commands, plano free e variaveis de ambiente —
   incluindo FIREBASE_CREDENTIALS_JSON (conteudo compacto do
   firebase-service-account.json local, NUNCA versionado).
4. Aguarda o primeiro deploy ficar 'live'.
5. Imprime a URL publica do servico.

Nenhum segredo e impresso no console.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

API_BASE = "https://api.render.com/v1"
# Repo padrao e o privado; repos publicos espelhos podem ser passados via env.
REPO_URL = os.environ.get(
    "RENDER_REPO_URL", "https://github.com/sergiochinelli/passagens-aereas"
)
SERVICE_NAME = "passagens-api"
SERVICE_ACCOUNT_FILE = Path(__file__).parent / "firebase-service-account.json"

POLL_INTERVAL = 20          # segundos entre checagens do deploy
POLL_TIMEOUT = 1800         # 30 min max (plano free compila devagar)


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _env_vars(service_account_json: str) -> list[dict]:
    database_url = os.environ.get("DATABASE_URL", "")
    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    if not database_url or not serpapi_key:
        raise SystemExit(
            "Defina DATABASE_URL e SERPAPI_KEY no ambiente antes de rodar."
        )
    return [
        {"key": "DATABASE_URL", "value": database_url},
        {"key": "SERPAPI_KEY", "value": serpapi_key},
        {"key": "SCHEDULER_ENABLED", "value": "true"},
        {"key": "SCHEDULER_TIMEZONE", "value": "America/Sao_Paulo"},
        {"key": "CORS_ORIGINS", "value": "*"},
        {"key": "FIREBASE_CREDENTIALS_JSON", "value": service_account_json},
        {"key": "FIREBASE_PROJECT_ID", "value": ""},
    ]


def get_owner_id(api_key: str) -> str:
    resp = requests.get(f"{API_BASE}/owners", headers=_headers(api_key), timeout=30)
    resp.raise_for_status()
    owners = resp.json()
    if not owners:
        raise SystemExit("Nenhum owner retornado pela API do Render.")
    return owners[0]["owner"]["id"]


def find_existing_service(api_key: str, owner_id: str) -> dict | None:
    resp = requests.get(
        f"{API_BASE}/services",
        headers=_headers(api_key),
        params={"name": SERVICE_NAME, "ownerId": owner_id, "limit": 20},
        timeout=30,
    )
    resp.raise_for_status()
    for item in resp.json():
        if item["service"]["name"] == SERVICE_NAME:
            return item["service"]
    return None


def create_service(api_key: str, owner_id: str, env_vars: list[dict]) -> dict:
    payload = {
        "type": "web_service",
        "name": SERVICE_NAME,
        "ownerId": owner_id,
        "repo": REPO_URL,
        "autoDeploy": "yes",
        "branch": "master",
        "envVars": env_vars,
        "serviceDetails": {
            "env": "python",
            "plan": "free",
            "region": "oregon",
            "envSpecificDetails": {
                "buildCommand": "pip install -r requirements.txt",
                "startCommand": (
                    "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
                ),
            },
        },
    }
    resp = requests.post(
        f"{API_BASE}/services", headers=_headers(api_key), json=payload, timeout=30
    )
    if not resp.ok:
        raise SystemExit(f"Falha ao criar servico: {resp.status_code} {resp.text[:400]}")
    return resp.json()["service"]


def wait_for_deploy(api_key: str, service_id: str) -> str:
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        resp = requests.get(
            f"{API_BASE}/services/{service_id}/deploys",
            headers=_headers(api_key),
            params={"limit": 1},
            timeout=30,
        )
        resp.raise_for_status()
        deploys = resp.json()
        if deploys:
            status = deploys[0]["deploy"]["status"]
            print(f"  deploy status: {status}")
            if status == "live":
                return status
            if status in {"build_failed", "canceled", "deactivated"}:
                raise SystemExit(f"Deploy falhou com status '{status}'.")
        time.sleep(POLL_INTERVAL)
    raise SystemExit("Timeout aguardando o deploy.")


def service_url(api_key: str, service_id: str) -> str:
    resp = requests.get(
        f"{API_BASE}/services/{service_id}", headers=_headers(api_key), timeout=30
    )
    resp.raise_for_status()
    return resp.json()["service"]["serviceDetails"]["url"]


def main() -> None:
    api_key = os.environ.get("RENDER_API_KEY", "")
    if not api_key:
        raise SystemExit("Defina RENDER_API_KEY no ambiente.")
    if not SERVICE_ACCOUNT_FILE.exists():
        raise SystemExit(f"Arquivo nao encontrado: {SERVICE_ACCOUNT_FILE}")
    sa_json = json.dumps(
        json.loads(SERVICE_ACCOUNT_FILE.read_text("utf-8")), separators=(",", ":")
    )

    owner_id = get_owner_id(api_key)
    print(f"ownerId: {owner_id}")
    print(f"repo: {REPO_URL}")

    service = find_existing_service(api_key, owner_id)
    if service:
        print(f"Servico ja existe: {service['id']} — atualizando env vars")
        resp = requests.put(
            f"{API_BASE}/services/{service['id']}/env-vars",
            headers=_headers(api_key),
            json=_env_vars(sa_json),
            timeout=30,
        )
        resp.raise_for_status()
    else:
        print("Criando web service...")
        service = create_service(api_key, owner_id, _env_vars(sa_json))
        print(f"Servico criado: {service['id']}")

    print("Aguardando deploy ficar live (pode levar varios minutos)...")
    wait_for_deploy(api_key, service["id"])

    url = service_url(api_key, service["id"])
    print(f"\nURL publica: {url}")
    print("Deploy concluido.")


if __name__ == "__main__":
    main()
