"""Testes da camada de autenticacao da API.

Cobre: login/logout/me, troca de senha, guarda global require_auth,
rotas publicas e formato legado v1 (AES-GCM).
"""

import pytest

from app.core.config import settings as app_settings
from app.core.security import encrypt_v1_password, hash_password

API = "/api/v1"


@pytest.fixture()
def auth_required(monkeypatch):
    monkeypatch.setattr(app_settings, "AUTH_REQUIRED", True)
    yield
    monkeypatch.setattr(app_settings, "AUTH_REQUIRED", False)


@pytest.fixture()
def auth_users(client, family_account):
    """Conta com setting auth_users (v1 + v2) ja populado."""
    fid = family_account["id"]
    # seed automatico da criacao de conta
    resp = client.get(f"{API}/settings?family_account_id={fid}&key=auth_users")
    assert resp.status_code == 200
    settings_list = resp.json()
    assert len(settings_list) == 1
    setting = settings_list[0]
    users = {u["login"]: u for u in setting["value"]["users"]}
    users["cris"]["pw"] = hash_password("senha-cris")
    users["cris"]["must_change"] = False
    resp = client.patch(f"{API}/settings/{setting['id']}", json={"value": {"users": list(users.values())}})
    assert resp.status_code == 200
    return fid, users


def _login(client, fid, login, password):
    return client.post(
        f"{API}/auth/login",
        json={"login": login, "password": password, "family_account_id": fid},
    )


# ------------------------- Login --------------------------


def test_login_v1_password(client, auth_users, auth_required):
    fid, _ = auth_users
    resp = _login(client, fid, "sergio", "1234")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["family_account_id"] == fid
    assert body["user"]["login"] == "sergio"
    assert body["user"]["must_change"] is True


def test_login_v2_password(client, auth_users, auth_required):
    fid, _ = auth_users
    resp = _login(client, fid, "cris", "senha-cris")
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["must_change"] is False


def test_login_wrong_password(client, auth_users, auth_required):
    fid, _ = auth_users
    assert _login(client, fid, "sergio", "errada").status_code == 401
    assert _login(client, fid, "ninguem", "1234").status_code == 401


def test_login_without_account_filter(client, auth_users, auth_required):
    resp = client.post(
        f"{API}/auth/login", json={"login": "cris", "password": "senha-cris"}
    )
    assert resp.status_code == 200


# --------------------- Guarda global ----------------------


def test_protected_route_requires_token(client, auth_users, auth_required):
    fid, _ = auth_users
    assert client.get(f"{API}/users?family_account_id={fid}").status_code == 401
    assert client.get(f"{API}/settings").status_code == 401
    assert client.get(f"{API}/routes").status_code == 401
    assert client.delete(f"{API}/family-accounts/{fid}").status_code == 401

    token = _login(client, fid, "cris", "senha-cris").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get(f"{API}/users?family_account_id={fid}", headers=headers).status_code == 200
    assert client.get(f"{API}/settings", headers=headers).status_code == 200


def test_public_routes_stay_open(client, auth_users, auth_required):
    fid, _ = auth_users
    assert client.get("/health").status_code == 200
    assert client.get(f"{API}/family-accounts").status_code == 200
    assert client.get(f"{API}/family-accounts/{fid}").status_code == 200
    resp = client.get(f"{API}/auth/users?family_account_id={fid}")
    assert resp.status_code == 200
    logins = {u["login"] for u in resp.json()}
    assert {"sergio", "cris"} <= logins
    assert all("pw" not in u for u in resp.json())


def test_settings_never_public(client, auth_users, auth_required):
    """O vazamento original: /settings nao pode responder sem token."""
    fid, _ = auth_users
    assert client.get(f"{API}/settings?family_account_id={fid}").status_code == 401


# --------------------- Sessao -----------------------------


def test_me_logout_flow(client, auth_users, auth_required):
    fid, _ = auth_users
    token = _login(client, fid, "cris", "senha-cris").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get(f"{API}/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["login"] == "cris"
    assert resp.json()["family_account_id"] == fid

    assert client.post(f"{API}/auth/logout", headers=headers).status_code == 204
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 401


def test_bogus_token_rejected(client, auth_users, auth_required):
    headers = {"Authorization": "Bearer token-inventado"}
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 401


def test_change_password(client, auth_users, auth_required):
    fid, _ = auth_users
    token = _login(client, fid, "cris", "senha-cris").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"{API}/auth/change-password",
        json={"current_password": "senha-cris", "new_password": "nova-senha-9"},
        headers=headers,
    )
    assert resp.status_code == 204

    # senha antiga nao entra mais; nova entra
    assert _login(client, fid, "cris", "senha-cris").status_code == 401
    assert _login(client, fid, "cris", "nova-senha-9").status_code == 200

    # sessao atual continua valida
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 200


def test_change_password_wrong_current(client, auth_users, auth_required):
    fid, _ = auth_users
    token = _login(client, fid, "cris", "senha-cris").json()["access_token"]
    resp = client.post(
        f"{API}/auth/change-password",
        json={"current_password": "errada", "new_password": "nova-senha-9"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


# ------------------ AUTH_REQUIRED=false -------------------


def test_reset_by_voucher(client, auth_users, auth_required):
    fid, _ = auth_users
    resp = client.post(
        f"{API}/auth/reset",
        json={
            "family_account_id": fid,
            "login": "sergio",
            "voucher_login": "cris",
            "voucher_password": "senha-cris",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["login"] == "sergio"
    temp = body["temporary_password"]

    # temporaria loga e exige troca
    login = _login(client, fid, "sergio", temp)
    assert login.status_code == 200
    assert login.json()["user"]["must_change"] is True

    # senha antiga morreu
    assert _login(client, fid, "sergio", "1234").status_code == 401


def test_reset_wrong_voucher(client, auth_users, auth_required):
    fid, _ = auth_users
    resp = client.post(
        f"{API}/auth/reset",
        json={
            "family_account_id": fid,
            "login": "sergio",
            "voucher_login": "cris",
            "voucher_password": "errada",
        },
    )
    assert resp.status_code == 401
    resp = client.post(
        f"{API}/auth/reset",
        json={
            "family_account_id": fid,
            "login": "sergio",
            "voucher_login": "sergio",
            "voucher_password": "1234",
        },
    )
    assert resp.status_code == 400  # avalista nao pode ser o proprio


def test_seed_endpoint(client, auth_required):
    resp = client.post(f"{API}/family-accounts", json={"name": "Familia Seed"})
    fid = resp.json()["id"]
    resp = client.post(f"{API}/auth/seed", json={"family_account_id": fid})
    assert resp.status_code == 200
    assert resp.json()["created"] is False  # ja semeada na criacao
    resp = client.post(f"{API}/auth/seed", json={"family_account_id": 99999})
    assert resp.status_code == 404


def test_open_mode_keeps_api_public(client, auth_users):
    """Com a flag desligada (transicao) tudo continua aberto."""
    fid, _ = auth_users
    assert client.get(f"{API}/settings?family_account_id={fid}").status_code == 200
    assert client.get(f"{API}/users?family_account_id={fid}").status_code == 200


def test_seed_on_account_creation(client):
    resp = client.post(f"{API}/family-accounts", json={"name": "Nova Familia"})
    assert resp.status_code == 201
    fid = resp.json()["id"]
    resp = client.get(f"{API}/settings?family_account_id={fid}&key=auth_users")
    users = resp.json()[0]["value"]["users"]
    assert {u["login"] for u in users} == {"sergio", "cris"}
    assert all(u["pw"].startswith("v1.") for u in users)
    assert all(u["must_change"] for u in users)


def test_encrypt_v1_roundtrip():
    stored = encrypt_v1_password("minha-senha")
    assert stored.startswith("v1.")
    from app.core.security import decrypt_v1_password, verify_any_password

    assert decrypt_v1_password(stored) == "minha-senha"
    assert verify_any_password("minha-senha", stored)
    assert not verify_any_password("outra", stored)
