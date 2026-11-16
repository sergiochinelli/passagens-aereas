# Passagens Aereas — Backend (Etapa 4)

API REST em **FastAPI** com persistencia em **PostgreSQL** (SQLAlchemy 2.x),
**integracao SerpApi — Google Flights**, **agendador APScheduler** e
**sistema de alertas push via Firebase Cloud Messaging** (Etapa 4).
Toda configuracao vem do arquivo `.env` — nenhum valor sensivel ou de
infraestrutura esta fixo no codigo.

## Novidades da Etapa 4 — Alertas FCM

```
app/services/notification.py  # FCMClient (HTTP legacy, chave via .env,
                              #  transporte injetavel) + NotificationService
                              #  (regras de alerta, mensagem, fan-out)
app/core/formatting.py        # format_brl -> "R$ 1.234.567,89"
```

### Regras de alerta (parametrizaveis por rota)

| Alerta | Condicao |
|---|---|
| `price_drop` | `alert_on_price_drop` e `lowest_price <= max_price` |
| `mixed_class` | `alert_on_mixed_class` e `has_mixed_class` |

### Fluxo

`search_route()` (agendado ou manual) persiste o `SearchResult` e chama
`NotificationService.notify_result(db, route, result)`:

1. Avalia os alertas disparados
2. Busca **todos os devices ativos** da `family_account_id` da rota
   (android e web — notificacao simultanea)
3. Envia um push por alerta por dispositivo, com `title`, `body`
   (preco em R$, companhia, trechos em classe mista) e payload `data`
   (alert_type, route_id, result_id, lowest_price, has_mixed_class)
4. Falhas individuais sao coletadas no `NotificationReport` — nunca
   quebram a busca persistida

### Endpoint auxiliar

`POST /api/v1/notifications/test` — envia push de teste a um device
cadastrado, para o painel validar o registro FCM.

### Configuracao (.env)

| Variavel | Default | Papel |
|---|---|---|
| `FCM_KEY` | (vazio) | Server key do Firebase — nunca no codigo |
| `FCM_ENDPOINT` | `https://fcm.googleapis.com/fcm/send` | Endpoint legacy HTTP |
| `FCM_TIMEOUT_SECONDS` | `15` | Timeout do envio |

## Estrutura (Etapa 1 + Etapa 2)

## Novidades da Etapa 3 — Agendador de monitoramento

```
app/services/scheduler.py   # RouteScheduler: 1 job por rota ativa,
                            # IntervalTrigger(monitor_interval_minutes),
                            # load_active_routes() no startup, sync via CRUD
```

### Como funciona

- **Fonte da verdade e o banco**: no startup, o lifespan inicia o
  `BackgroundScheduler` e chama `load_active_routes()` — todas as rotas com
  `is_active=true` recebem um job `route_monitor_{id}`.
- **Intervalo por rota**: cada job usa `IntervalTrigger(minutes=
  route.monitor_interval_minutes)` — configuravel pelo painel, zero hardcode.
- **Execucao**: o job `run_route_check(route_id)` abre sessao propria,
  recarrega a rota (com legs), verifica `is_active` e chama
  `FlightSearchService.search_route(db, route, triggered_by="scheduled")`.
  Erros SerpApi sao logados sem derrubar o scheduler; se a rota foi
  removida/desativada, o job se auto-remove.
- **Sincronizacao com CRUD**: criar rota ativa → job criado; PATCH → job
  reagendado (ou removido se `is_active=false`); DELETE → job removido.
- **Disparo manual**: `POST /api/v1/routes/{id}/trigger`
  (alias de `/routes/{id}/search`) executa imediatamente e persiste.
- **Status**: `GET /api/v1/scheduler/status` lista jobs e proximas execucoes.

### Configuracao (.env)

| Variavel | Default | Papel |
|---|---|---|
| `SCHEDULER_ENABLED` | `true` | Liga/desliga o agendador |
| `SCHEDULER_TIMEZONE` | `UTC` | Fuso dos jobs (ex.: America/Sao_Paulo) |
| `SCHEDULER_MISFIRE_GRACE_SECONDS` | `300` | Tolerancia para execucao atrasada |
| `SCHEDULER_MAX_INSTANCES` | `1` | Execucoes simultaneas por job |
| `SCHEDULER_COALESCE` | `true` | Junta execucoes perdidas em uma so |

## Estrutura (Etapa 1 + Etapa 2)

## Novidades da Etapa 2 — Integracao SerpApi

```
app/services/
├── serpapi_client.py    # Cliente HTTP da SerpApi (httpx, chave via .env,
│                        #  transporte injetavel p/ testes, SerpApiError)
└── flight_search.py     # FlightSearchService: traduz criterios -> parametros
                         #  da API, normaliza opcoes, detecta classe mista,
                         #  persiste melhor opcao em search_results
app/schemas/flight_search.py  # SearchCriteria, FlightOption, LegDetail,
                              #  LayoverDetail, MixedClassDetail
app/api/routes/search.py      # POST /api/v1/search (avulsa)
                              # POST /api/v1/routes/{id}/search (disparo manual)
```

### Tipos de viagem suportados

| `trip_type` | `type` SerpApi | Parametros usados |
|---|---|---|
| `round_trip` | 1 | `departure_id`, `arrival_id`, `outbound_date`, `return_date` |
| `one_way` | 2 | `departure_id`, `arrival_id`, `outbound_date` |
| `multi_city` | 3 | `multi_city_json` (array de trechos com datas) |

### Dados capturados por opcao de voo

- `price`, `currency`, `airlines[]` (companhias de todos os trechos)
- `total_duration_minutes`, `stops`, `layovers[]` (aeroporto + tempo de conexao)
- `legs[]` por trecho: origem/destino, horarios, companhia, numero do voo,
  **classe encontrada**, duracao, flag overnight
- `has_mixed_class` + `mixed_class_details[]` (trecho, classe esperada vs.
  encontrada) — detector compara a classe solicitada com cada leg
- `booking_token` para referencia futura de compra

### Fluxo de persistencia

`POST /api/v1/routes/{id}/search` executa a busca, grava a melhor opcao
(menor preco) em `search_results` com `triggered_by="manual"`, salva o
payload bruto para auditoria e atualiza `last_checked_at` da rota.
O mesmo caminho sera chamado pelo agendador da Etapa 3.

## Estrutura (Etapa 1 + Etapa 2)

## Estrutura

```
backend/
├── .env                  # Configuracao local (SERPAPI_KEY, FCM_KEY, DATABASE_URL)
├── .env.example          # Template do .env
├── requirements.txt
├── pytest.ini
├── app/
│   ├── main.py           # FastAPI app, /health, include_router /api/v1
│   ├── core/
│   │   ├── config.py     # Settings via pydantic-settings (.env)
│   │   └── security.py   # Hash PBKDF2-HMAC-SHA256 de senhas
│   ├── db/
│   │   ├── base.py       # DeclarativeBase
│   │   └── session.py    # engine, SessionLocal, get_db
│   ├── models/           # SQLAlchemy ORM
│   │   ├── family_account.py   # Conta familiar (agrupa tudo)
│   │   ├── user.py             # Usuario (perfil da conta)
│   │   ├── monitored_route.py  # Rota monitorada + parametros de alerta
│   │   ├── route_leg.py        # Trechos de rotas multi_city
│   │   ├── search_result.py    # Historico de resultados/precos
│   │   ├── device.py           # Dispositivos push (android/web, token FCM)
│   │   └── setting.py          # Chave-valor de parametrizacao por conta
│   ├── schemas/          # Pydantic (validacao de entrada/saida)
│   └── api/
│       ├── deps.py       # Injecao de sessao do banco
│       └── routes/       # CRUD: family-accounts, users, routes,
│                         #       search-results, devices, settings
└── tests/                # Suite funcional (pytest + TestClient)
```

## Modelo de dados

| Tabela | Papel |
|---|---|
| `family_accounts` | Conta familiar (plano compartilhado) |
| `users` | Perfis sob a conta; `email` unico; senha em hash PBKDF2 |
| `monitored_routes` | Rota: tipo (`round_trip`/`one_way`/`multi_city`), datas, passageiros, classe, `max_price`, `monitor_interval_minutes`, filtros de companhias, flags de alerta |
| `route_legs` | Trechos ordenados para rotas `multi_city` |
| `search_results` | Resultado de cada consulta: preco, companhia, duracao, escalas (`layovers`), detalhe por trecho, `has_mixed_class`, payload bruto |
| `devices` | Tokens FCM por plataforma (`android`/`web`) para push simultaneo |
| `settings` | Parametrizacao chave-valor por conta familiar |

## Endpoints (`/api/v1`)

Todos os recursos expoem CRUD completo:

| Recurso | Metodos |
|---|---|
| `/family-accounts` | GET (lista), POST, GET/{id}, PATCH/{id}, DELETE/{id} |
| `/users` | GET (lista, filtro `family_account_id`), POST, GET/{id}, PATCH/{id}, DELETE/{id} |
| `/routes` | GET (lista, filtros `family_account_id`, `is_active`), POST, GET/{id}, PATCH/{id}, DELETE/{id} |
| `/search-results` | GET (lista, filtro `route_id`), POST, GET/{id}, DELETE/{id} |
| `/devices` | GET (lista, filtros), POST, GET/{id}, PATCH/{id}, DELETE/{id} |
| `/settings` | GET (lista, filtros `family_account_id`, `key`), POST, GET/{id}, PATCH/{id}, DELETE/{id} |
| `/search` | POST — busca avulsa (nao persiste), retorna opcoes normalizadas |
| `/routes/{id}/search` | POST — disparo manual, persiste SearchResult |
| `/routes/{id}/trigger` | POST — alias oficial do disparo manual imediato |
| `/scheduler/status` | GET — jobs agendados e proximas execucoes |
| `/notifications/test` | POST — push de teste para um device |
| `/health` | GET |

Regras de validacao relevantes:
- `round_trip` exige `return_date`; `one_way`/`round_trip` exigem `origin`,
  `destination` e `departure_date`.
- `multi_city` exige ao menos 2 `legs` (ignora `origin`/`destination` diretos).
- `email` de usuario unico (409 em duplicidade); `fcm_token` unico (409);
  `settings` tem chave unica por conta (409 — atualizar via PATCH).
- Senhas nunca sao retornadas nos payloads de leitura.

## Como executar

```bash
cd backend
pip install -r requirements.txt
# Edite .env: DATABASE_URL apontando para o PostgreSQL, SERPAPI_KEY, FCM_KEY
uvicorn app.main:app --reload
```

Docs interativas: `http://localhost:8000/docs`

## Testes

```bash
cd backend
pytest
```

Os testes usam **SQLite em memoria** via override de `DATABASE_URL`
(o SQLAlchemy abstrai o dialeto; em producao basta o `.env` com a URL
PostgreSQL). Cobrem CRUD completo de todos os recursos, validacoes de
regra de negocio e codigos de erro (404/409/422).

A camada SerpApi e testada **sem rede real**: `httpx.MockTransport`
substitui o transporte HTTP e fixtures em `tests/fixtures/` reproduzem
respostas reais do engine `google_flights`. A `SERPAPI_KEY` nunca e
solicitada em codigo nem exposta — em testes usa-se chave ficticia.

## Notas para as proximas etapas

- `app.main:lifespan` cria tabelas no startup — sera substituido por
  migrations (Alembic) quando o esquema estabilizar.
- O backend esta funcionalmente completo: busca -> persistencia ->
  agendamento -> alerta. Etapas 5 e 6 sao apenas os clientes (React e
  React Native) consumindo `/api/v1`.
- Migracao Supabase: basta trocar `DATABASE_URL` no `.env`.

## Novidades da Etapa 5 � Autenticacao da API

`
app/models/auth_session.py      # AuthSession: token opaco, so o SHA-256 vai pro banco
app/services/auth_service.py    # login contra auth_users, sessoes, seed, reset
app/api/routes/auth.py          # /auth/login, /users, /me, /logout,
                                #  /change-password, /reset, /seed
app/api/deps.py                 # require_auth: guarda global (AUTH_REQUIRED)
`

### Como funciona

- POST /api/v1/auth/login verifica a senha **no servidor** e devolve um
  Bearer token (expira em AUTH_TOKEN_TTL_HOURS, padrao 30 dias).
- equire_auth e dependencia de todos os routers quando
  AUTH_REQUIRED=true. Rotas publicas minimas: /health, /auth/*,
  GET/POST /family-accounts (selecao e criacao de conta, pre-login).
- Senhas: o formato legado 1. (AES-GCM do frontend antigo) ainda e
  aceito no login; toda gravacao nova usa PBKDF2 (nao reversivel).
- POST /auth/reset implementa o aval familiar: outro usuario da mesma
  conta confirma a propria senha e o sistema gera senha temporaria com
  must_change=true.
- POST /family-accounts semeia uth_users no servidor � o frontend
  nao precisa mais escrever credenciais.
- Logout e troca de senha revogam sessoes (token vira 401 na hora).

### Rollout

1. Backend sobe com AUTH_REQUIRED=false (default) � API segue aberta,
   endpoints /auth/* ja funcionais.
2. Frontend publicado passa a emitir token apos o login.
3. AUTH_REQUIRED=true no ambiente tranca todas as rotas protegidas.
