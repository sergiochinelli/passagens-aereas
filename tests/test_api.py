"""Testes funcionais de todos os endpoints CRUD - Etapa 1.

Cobertura: family-accounts, users, routes (+legs), search-results,
devices, settings e health check.
"""

API = "/api/v1"


# ------------------------- Health -------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# -------------------- Family Accounts ---------------------

def test_family_account_crud(client):
    # Create
    resp = client.post(f"{API}/family-accounts", json={"name": "Familia Teste"})
    assert resp.status_code == 201
    account = resp.json()
    assert account["name"] == "Familia Teste"
    assert account["is_active"] is True

    # Read
    resp = client.get(f"{API}/family-accounts/{account['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == account["id"]

    # List
    resp = client.get(f"{API}/family-accounts")
    assert resp.status_code == 200
    assert any(a["id"] == account["id"] for a in resp.json())

    # Update
    resp = client.patch(
        f"{API}/family-accounts/{account['id']}", json={"name": "Familia Editada"}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Familia Editada"

    # Delete
    resp = client.delete(f"{API}/family-accounts/{account['id']}")
    assert resp.status_code == 204
    assert client.get(f"{API}/family-accounts/{account['id']}").status_code == 404


def test_family_account_not_found(client):
    assert client.get(f"{API}/family-accounts/99999").status_code == 404


# ------------------------- Users --------------------------

def test_user_crud(client, family_account):
    fid = family_account["id"]

    # Create
    payload = {
        "family_account_id": fid,
        "full_name": "Sergio Costa",
        "email": "sergio@teste.com",
        "password": "senha123",
        "role": "admin",
    }
    resp = client.post(f"{API}/users", json=payload)
    assert resp.status_code == 201
    user = resp.json()
    assert user["email"] == "sergio@teste.com"
    assert "password" not in user
    assert "password_hash" not in user

    # Email duplicado -> 409
    resp = client.post(f"{API}/users", json=payload)
    assert resp.status_code == 409

    # Conta inexistente -> 404
    resp = client.post(
        f"{API}/users", json={**payload, "family_account_id": 99999, "email": "x@x.com"}
    )
    assert resp.status_code == 404

    # Read
    resp = client.get(f"{API}/users/{user['id']}")
    assert resp.status_code == 200

    # List filtrado por conta
    resp = client.get(f"{API}/users?family_account_id={fid}")
    assert resp.status_code == 200
    assert any(u["id"] == user["id"] for u in resp.json())

    # Update
    resp = client.patch(
        f"{API}/users/{user['id']}",
        json={"full_name": "Sergio C.", "password": "novasenha1"},
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Sergio C."

    # Delete
    assert client.delete(f"{API}/users/{user['id']}").status_code == 204
    assert client.get(f"{API}/users/{user['id']}").status_code == 404


# --------------------- Monitored Routes -------------------

def _route_payload(fid, **overrides):
    payload = {
        "family_account_id": fid,
        "trip_type": "round_trip",
        "origin": "GRU",
        "destination": "MIA",
        "departure_date": "2026-12-10",
        "return_date": "2026-12-20",
        "passengers": 2,
        "travel_class": "economy",
        "max_price": "4500.00",
        "currency": "BRL",
        "monitor_interval_minutes": 30,
        "alert_on_price_drop": True,
        "alert_on_mixed_class": True,
        "airlines_include": ["LA", "AA", "G3"],
        "airlines_exclude": [],
        "is_active": True,
    }
    payload.update(overrides)
    return payload


def test_route_round_trip_crud(client, family_account):
    fid = family_account["id"]

    # Create
    resp = client.post(f"{API}/routes", json=_route_payload(fid))
    assert resp.status_code == 201, resp.text
    route = resp.json()
    assert route["origin"] == "GRU"
    assert route["max_price"] == "4500.00"

    # Read
    resp = client.get(f"{API}/routes/{route['id']}")
    assert resp.status_code == 200
    assert resp.json()["trip_type"] == "round_trip"

    # List + filtros
    resp = client.get(f"{API}/routes?family_account_id={fid}&is_active=true")
    assert resp.status_code == 200
    assert any(r["id"] == route["id"] for r in resp.json())

    # Update de parametros do painel (preco maximo, frequencia, classe)
    resp = client.patch(
        f"{API}/routes/{route['id']}",
        json={"max_price": "3900.00", "monitor_interval_minutes": 15,
              "travel_class": "business"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_price"] == "3900.00"
    assert body["monitor_interval_minutes"] == 15
    assert body["travel_class"] == "business"

    # Delete
    assert client.delete(f"{API}/routes/{route['id']}").status_code == 204
    assert client.get(f"{API}/routes/{route['id']}").status_code == 404


def test_route_one_way(client, family_account):
    payload = _route_payload(
        family_account["id"], trip_type="one_way", return_date=None
    )
    resp = client.post(f"{API}/routes", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["return_date"] is None


def test_route_multi_city_with_legs(client, family_account):
    payload = _route_payload(
        family_account["id"],
        trip_type="multi_city",
        origin=None,
        destination=None,
        departure_date=None,
        return_date=None,
        legs=[
            {"leg_order": 1, "origin": "GRU", "destination": "LIS",
             "departure_date": "2026-12-10"},
            {"leg_order": 2, "origin": "LIS", "destination": "MAD",
             "departure_date": "2026-12-15"},
            {"leg_order": 3, "origin": "MAD", "destination": "GRU",
             "departure_date": "2026-12-22"},
        ],
    )
    resp = client.post(f"{API}/routes", json=payload)
    assert resp.status_code == 201, resp.text
    route = resp.json()
    assert len(route["legs"]) == 3
    assert route["legs"][0]["origin"] == "GRU"
    assert route["legs"][2]["destination"] == "GRU"


def test_route_validation_errors(client, family_account):
    fid = family_account["id"]

    # round_trip sem return_date -> 422
    resp = client.post(
        f"{API}/routes", json=_route_payload(fid, return_date=None)
    )
    assert resp.status_code == 422

    # multi_city com menos de 2 legs -> 422
    resp = client.post(
        f"{API}/routes",
        json=_route_payload(
            fid, trip_type="multi_city", origin=None, destination=None,
            departure_date=None, return_date=None,
            legs=[{"leg_order": 1, "origin": "GRU", "destination": "LIS",
                   "departure_date": "2026-12-10"}],
        ),
    )
    assert resp.status_code == 422

    # Conta inexistente -> 404
    resp = client.post(f"{API}/routes", json=_route_payload(99999))
    assert resp.status_code == 404


# --------------------- Search Results ---------------------

def test_search_result_crud(client, family_account):
    resp = client.post(f"{API}/routes", json=_route_payload(family_account["id"]))
    route_id = resp.json()["id"]

    payload = {
        "route_id": route_id,
        "triggered_by": "manual",
        "lowest_price": "3890.50",
        "currency": "BRL",
        "airline": "LATAM",
        "total_duration_minutes": 600,
        "stops": 1,
        "layovers": [{"airport": "PTY", "duration_minutes": 95}],
        "legs_detail": [
            {"leg": 1, "class": "economy", "airline": "LA"},
            {"leg": 2, "class": "business", "airline": "LA"},
        ],
        "has_mixed_class": True,
        "mixed_class_details": [{"leg": 2, "expected": "economy", "found": "business"}],
        "raw_payload": {"provider": "serpapi", "source": "google_flights"},
    }
    resp = client.post(f"{API}/search-results", json=payload)
    assert resp.status_code == 201, resp.text
    result = resp.json()
    assert result["has_mixed_class"] is True
    assert result["lowest_price"] == "3890.50"

    # List por rota (historico de precos)
    resp = client.get(f"{API}/search-results?route_id={route_id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Read / Delete
    assert client.get(f"{API}/search-results/{result['id']}").status_code == 200
    assert client.delete(f"{API}/search-results/{result['id']}").status_code == 204

    # Rota inexistente -> 404
    resp = client.post(
        f"{API}/search-results", json={**payload, "route_id": 99999}
    )
    assert resp.status_code == 404


# ------------------------- Devices ------------------------

def test_device_crud(client, family_account):
    fid = family_account["id"]

    payload = {
        "family_account_id": fid,
        "platform": "android",
        "fcm_token": "fcm-token-android-0001",
        "label": "Moto G Sergio",
    }
    resp = client.post(f"{API}/devices", json=payload)
    assert resp.status_code == 201
    device = resp.json()
    assert device["platform"] == "android"

    # Token duplicado -> 409
    resp = client.post(f"{API}/devices", json=payload)
    assert resp.status_code == 409

    # Segundo dispositivo (web)
    resp = client.post(
        f"{API}/devices",
        json={**payload, "platform": "web", "fcm_token": "fcm-token-web-0002",
              "label": "Chrome PC"},
    )
    assert resp.status_code == 201

    # List por conta -> 2 dispositivos (notificacao simultanea)
    resp = client.get(f"{API}/devices?family_account_id={fid}")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    # Update / Delete
    resp = client.patch(
        f"{API}/devices/{device['id']}", json={"is_active": False}
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    assert client.delete(f"{API}/devices/{device['id']}").status_code == 204


# ------------------------- Settings -----------------------

def test_setting_crud(client, family_account):
    fid = family_account["id"]

    payload = {
        "family_account_id": fid,
        "key": "default_monitor_interval_minutes",
        "value": {"minutes": 30},
    }
    resp = client.post(f"{API}/settings", json=payload)
    assert resp.status_code == 201
    setting = resp.json()

    # Chave duplicada na mesma conta -> 409
    resp = client.post(f"{API}/settings", json=payload)
    assert resp.status_code == 409

    # Mesma chave em outra conta -> permitido
    resp2 = client.post(f"{API}/family-accounts", json={"name": "Outra Familia"})
    other_fid = resp2.json()["id"]
    resp = client.post(
        f"{API}/settings", json={**payload, "family_account_id": other_fid}
    )
    assert resp.status_code == 201

    # Filtro por chave
    resp = client.get(f"{API}/settings?family_account_id={fid}&key=default_monitor_interval_minutes")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Update / Delete
    resp = client.patch(
        f"{API}/settings/{setting['id']}", json={"value": {"minutes": 45}}
    )
    assert resp.status_code == 200
    assert resp.json()["value"]["minutes"] == 45
    assert client.delete(f"{API}/settings/{setting['id']}").status_code == 204
