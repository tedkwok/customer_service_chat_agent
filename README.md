# Store Customer Service — Event-Driven AI Agent Platform

An LLM-powered customer service agent for an online store. Customers log in through a
React SPA, chat with a multi-agent system over the AG-UI protocol (SSE), and the agent
answers policy/product questions (RAG), looks up accounts and purchase history, and
executes purchases, refunds, and membership registration — with human-in-the-loop
approval for irreversible actions (refunds).

The web layer and the agent execution layer are decoupled by a Redis pub/sub event bus:
HTTP requests are accepted by the web process, published as events, processed by
independent worker processes, and streamed back to the right client connection.

---

## 1. High-Level Architecture

```
                                   ┌────────────────────────── Docker network ──────────────────────────┐
                                   │                                                                      │
 ┌──────────────┐   POST /stream   │  ┌─────────────────┐        Redis Pub/Sub (event bus)               │
 │  React SPA   │  /api /oauth     │  │  agent-server   │  channel: agent_request_queue                  │
 │ (Vite :5173) │ ────────────────▶│  │  (FastAPI :8000)│──▶ [N request receivers]──┐                     │
 │              │   SSE stream     │  │                 │                           ▼                     │
 │  @ag-ui/     │ ◀────────────────│  │  Connection     │                    ┌─────────────┐               │
 │  client      │                  │  │  Manager        │                    │   Redis 7   │               │
 └──────────────┘                  │  └─────────────────┘                    │ (shared)    │               │
                                   │            ▲                            └──────┬──────┘               │
                                   │            │ channel: agent_response_          │                      │
                                   │            │ queue  [M response                   │                      │
                                   │            │ distributors]◀──────────────────────┤                      │
                                   │            │                                    │ SUBSCRIBE            │
                                   │            │                                    ▼                      │
                                   │            │                          ┌──────────────────┐            │
                                   │            └── per-connection SSE ────│  K request worker │            │
                                   │                 asyncio queues        │  processes       │            │
                                   │                                        │ (multiprocessing) │            │
                                   │                                        └────────┬─────────┘            │
                                   │                                                 │                      │
                                   │      ┌─────────────── LLM call path ────────────┘                      │
                                   │      │                                                                │
                                   │      ▼                                                                │
                                   │  ┌────────────┐  guardrails   ┌───────────────┐   ┌──────────────────┐ │
                                   │  │  litellm   │──(pre/post)──▶│ guardrails/   │   │ vllm-embedding   │ │
                                   │  │ gateway    │               │ (PII, inject) │   │ (multilingual-   │ │
                                   │  │ (:4000)    │               └───────────────┘   │  e5-large, CPU)  │ │
                                   │  └─────┬──────┘                                   └──────────────────┘ │
                                   │        ▼  Z.AI API (glm-5.3 / 5.2 / 5.1)                              │
                                   │                                                                        │
                                   │  ┌────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌──────────────┐    │
                                   │  │ MySQL 8│ │ Postgres │ │ ChromaDB│ │ Langfuse│ │ OTel → Zipkin│    │
                                   │  │ business│ │ 17 store │ │ vectors │ │ + CH +  │ │   (:9411)    │    │
                                   │  │ + checkpt│ │          │ │ (:8001) │ │ MinIO   │ │              │    │
                                   │  └────────┘ └──────────┘ └─────────┘ └─────────┘ └──────────────┘    │
                                   └────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Structure

### 2.1 Services (docker-compose.yaml)

| Service | Image / Build | Port(s) | Role |
|---|---|---|---|
| `frontend` | node:22-alpine (Vite dev server) | 5173 | React SPA; proxies `/api`, `/oauth`, `/stream` to agent-server |
| `agent-server` | Built from `Dockerfile` (python:3.12-slim) | 8000 | FastAPI app: auth, account, AG-UI streaming endpoint, event bus web side |
| `litellm` | ghcr.io/berriai/litellm | 4000 | LLM gateway: model routing, fallbacks, custom guardrails |
| `postgres_litellm` | postgres:16-alpine | — | LiteLLM's own state (keys, spend) |
| `vllm-embedding` | vllm/vllm-openai-cpu | 8002→8000 | CPU embedding server (`intfloat/multilingual-e5-large`) |
| `redis` | redis:7 | 6379 | **Shared**: event bus pub/sub + distributed locks (agent) and BullMQ queues (Langfuse) |
| `mysql` | mysql:8.0 | 3306 | Business data (`app_db`) + LangGraph MySQL checkpointer (conversation state) |
| `postgres` | postgres:17 | 5432 | **Shared**: Langfuse tables + LangGraph `AsyncPostgresStore` (cross-thread memory) |
| `chroma` | chromadb/chroma | 8001→8000 | Vector store for the knowledge base |
| `langfuse-web` / `langfuse-worker` | langfuse:4 | 3000 / 3030 | LLM observability (traces, prompts) |
| `clickhouse` / `minio` | — | 8123, 9000 / 9090 | Langfuse analytics storage + object storage |
| `otel-collector` / `zipkin` | otel-contrib 0.111 / openzipkin | — / 9411 | OpenTelemetry trace collection and viewing |

### 2.2 Backend package layout (`app/`)

```
app/
├── main.py                  # FastAPI app: lifespan startup, /stream/{user_id}, /actuator/health
├── event_bus/               # ★ Event-driven core (see §4)
│   ├── request_submit.py       # request receivers (asyncio tasks) → publish to Redis
│   ├── request_worker.py       # worker processes: subscribe, run agent, publish responses
│   ├── response_receive.py     # response distributors + per-connection SSE generators
│   └── connection_manager.py   # connection registry, least-loaded routing, per-connection queues
├── agent/
│   ├── implementation.py       # LangGraph astream_events(v2) → AG-UI event translation
│   ├── agent/
│   │   ├── coordinator.py      # deepagents create_deep_agent (root agent)
│   │   ├── subagent.py         # knowledge_agent + operation_agent definitions
│   │   ├── llm_provider.py     # ChatLiteLLMRouter with model fallback chain
│   │   ├── memory.py           # MySQL checkpointer + episodic-memory search tool
│   │   ├── human_in_the_loop.py# HumanInTheLoopMiddleware (refund approval interrupt)
│   │   ├── copilotkit_middleware.py
│   │   ├── prompt.py           # system prompts per agent
│   │   └── tracing.py          # Langfuse callback handler
│   └── tools/
│       ├── vector_search.py    # hybrid search + query expansion over Chroma
│       ├── operation.py        # MySQL-backed business tools (purchase, refund, ...)
│       ├── render_tools.py     # AG-UI tool calls the frontend renders as cards
│       └── agent_tool_stack.py # timestamp + sandboxed pandas REPL
├── routers/
│   ├── auth.py                 # register, JWT, OAuth2 authorization-code flow
│   └── account.py              # /topup
├── BaseModel/                  # Pydantic v2 models (Request, Response, context, ...)
├── connection/                 # redis (async/cluster), mysql (SQLAlchemy), aiomysql
└── utils/                      # augi_parse, circuit_breaker, identity_checker,
                                # response_checker (approval wording detection)
guardrails/                     # LiteLLM custom guardrails (mounted into litellm container)
knowledge_base/                 # Markdown docs: store policy, refund policy, membership, catalogue
scripts/                        # ingestion, demo data seeding, smoke tests
frontend/src/                   # React app: pages (Login, Register, Callback, Chat, TopUp),
                                # components (RenderComponents.tsx), auth.ts
```

### 2.3 Agent organization (multi-agent)

- **Coordinator (root)** — built with `deepagents.create_deep_agent`; owns the customer
  conversation, episodic memory search, and render tools; delegates to subagents.
- **knowledge_agent** — RAG over `knowledge_base/` via Chroma hybrid search and
  multi-query expansion (`get_document_by_hybrid_search`, `get_document_by_query_expansion`).
- **operation_agent** — business tools against MySQL: `get_customer_history`,
  `check_customer_info`, `register_membership`, `get_product_info`, `purchase`,
  `refund`, plus `get_current_timestamp` and `analyze_pandas_dataset`.

Render tools (`render_product_card`, `render_membership_status`,
`render_purchase_summary`, `render_refund_status`) are surfaced to the UI as AG-UI
`ToolCall*` events and rendered by `frontend/src/components/RenderComponents.tsx`.

---

## 3. Technology, Packages and Languages

### Languages
- **Python 3.12** — backend (FastAPI service, agent, workers, guardrails, scripts)
- **TypeScript 5.5 / React 18** — frontend SPA
- **YAML / Dockerfile / shell** — deployment configuration

### Backend (key packages from `requirements.txt`)

| Area | Packages |
|---|---|
| API framework | `fastapi`, `uvicorn`, `pydantic` v2, `jinja2`, `python-multipart` |
| Agent orchestration | `langgraph`, `langchain` 1.x, `langchain-classic`, `deepagents`, `copilotkit` |
| LLM access | `litellm` (client + gateway), `langchain-litellm` (Router w/ fallback chain) |
| Protocol | `ag-ui-protocol` (AG-UI SSE event encoding) |
| Memory / state | `langgraph-checkpoint-mysql[aiomysql]`, `langgraph-checkpoint-postgres`, `pymysql`, `aiomysql`, `psycopg-binary` |
| Vector store / RAG | `chromadb`, `langchain-chroma`, `llama-index-core` (ingestion chunking), `langchain-experimental` (pandas REPL) |
| Data | `SQLAlchemy` 2, `pandas`, `trino`, `neonize` |
| Auth | `pyjwt[crypto]` |
| Resilience | `tenacity`, `pybreaker`, `aiobreaker`, `redis` (locks, idempotency) |
| Observability | `langfuse` 3.x callback handler |
| Config | `python-dotenv` |

### Frontend (from `frontend/package.json`)
`react`, `react-dom` (18.3), `react-router-dom` 6, `@ag-ui/client` 1.0 (AG-UI `HttpAgent`
that POSTs `RunAgentInput` and consumes the SSE event stream), built with
`vite` 5 + `@vitejs/plugin-react`, type-checked with `typescript` 5.5.

### Models (via `litellm_config.yaml`)
- **Chat**: Z.AI `glm-5.3` / `glm-5.2` / `glm-5.1` (OpenAI-compatible endpoint), exposed
  through the LiteLLM gateway with latency-based routing; the app requests the stable
  alias `customer-service-llm` and LiteLLM falls back across deployments.
- **Embeddings**: `intfloat/multilingual-e5-large` served CPU-only by vLLM, proxied
  through the gateway as `multilingual-e5-large`.

---

## 4. Event-Driven Architecture

The service uses **Redis Pub/Sub as an internal event bus** to decouple the HTTP/web
layer from agent execution, allowing both sides to scale independently.

### Channels
| Channel (env-configurable) | Producer | Consumers |
|---|---|---|
| `agent_request_queue` (`EVENT_BUS_REQUEST_QUEUE`) | Request receivers (web process) | Request workers (separate processes) |
| `agent_response_queue` (`EVENT_BUS_RESPONSE_QUEUE`) | Request workers | Response distributors (web process) |

### Event bus roles

1. **Request receivers** (`app/event_bus/request_submit.py`) — `NUMBER_REQUEST_RECEIVER`
   (default 8) asyncio tasks in the web process. Each drains its own asyncio queue and
   publishes a JSON request event `{connection_id, user_id, thread_id, request_body}`
   (the newest user message extracted from the AG-UI `RunAgentInput`).

2. **Request workers** (`app/event_bus/request_worker.py`) — `NUMBER_REQUEST_WORKER`
   (default 8) **separate `multiprocessing.Process`es**, each running its own event loop
   subscribed to the request channel. On a message, a worker acquires a **Redis
   distributed lock keyed by `connection_id`** (non-blocking, 10 s TTL) so exactly one
   worker handles a given connection's request. It runs the coordinator agent and
   publishes **each AG-UI event** as an individual `Response` message to the response
   channel (streaming is preserved end-to-end; events are split at 8 000 chars to stay
   under the 10 000-char `Response` validation cap).

3. **Response distributors** (`app/event_bus/response_receive.py`) —
   `NUMBER_RESPONSE_DISTRIBUTOR` (default 8) asyncio tasks in the web process, all
   subscribed to the response channel. Each message is routed by `connection_id`; only
   the distributor that owns the connection delivers it into that connection's private
   asyncio queue, which feeds the SSE `StreamingResponse`.

4. **ConnectionManager** (`app/event_bus/connection_manager.py`) — registry of live
   SSE connections. On `connect()` it assigns each connection the **least-loaded**
   request receiver and response distributor (first an unused one, else the one with
   fewest active connections), creates the per-connection queues and the submit/receive
   objects; on `disconnect()` everything is cleaned up.

### Why this design
- **Decoupling** — web handlers never call the agent directly; slow LLM work cannot
  block the request path of other clients.
- **Parallelism model** — receivers/distributors are asyncio tasks (share the
  per-connection queues), workers are true processes (CPU/IO isolation for agent runs).
- **Horizontal scaling** — every stage is fan-out/fan-in over pub/sub; counts are
  env-tunable, and workers could move to separate hosts since coordination is via Redis.
- **Delivery guarantees** — per-connection locks prevent duplicate handling; JWT-tokenized
  idempotency keys (`redis.set(..., nx=True, ex=TTL)`) guard against duplicate submits.
- **Backpressure-friendly routing** — least-loaded assignment spreads connections evenly.

---

## 5. User Request Handling Cycle

End-to-end lifecycle of one customer chat turn:

```
 Browser                agent-server (web process)            Redis                worker process
 ───────                ───────────────────────────           ─────                ──────────────
   │ 1. login (JWT /                                          │
   │    OAuth2 auth-code)                                     │
   │ 2. POST /stream/{user_id}  ──▶ ConnectionManager.connect │
   │    (RunAgentInput)            (assign receiver+distributor,
   │                               per-connection queues)      │
   │                               3. submit_request ──▶ PUBLISH ──▶ 4. SUBSCRIBE, acquire
   │                                                                  Redis lock(connection_id)
   │                                                                5. build coordinator agent
   │                                                                   (MySQL checkpointer,
   │                                                                    Postgres store)
   │                                                                6. approval wording? ──┐
   │                                ┌─────────────────────────────┘                        │
   │                                │ no │                   yes: Command(resume) for the
   │                                │   │                        pending refund interrupt
   │                                │   │                   7. agent.astream_events(v2)
   │                                │   │                   8. LangGraph events → AG-UI
   │                                │   │                      events (RunStarted, TextMessage*,
   │                                │   │                      ToolCall*, RunFinished)
   │                                │   │ 9. each event → PUBLISH ◀────────────────────────┤
   │ 10. SSE:                    ◀──│── per-connection queue ◀── SUBSCRIBE (distributor) ──┤
   │     text deltas, tool-call       │   routes by connection_id
   │     render events                │
   │ 11. stream ends / client close ─▶ ConnectionManager.disconnect (cleanup)
```

1. **Authentication** — the customer registers/logs in (`/api/auth/register`,
   `/oauth/authorize` + `/oauth/token` authorization-code flow, JWT access tokens);
   `/api/auth/me` identifies the session, `/topup` manages balance.
2. **Submit** — the Chat page's AG-UI `HttpAgent` POSTs a `RunAgentInput` to
   `POST /stream/{user_id}`. The endpoint mints a `connection_id`
   (`user_id` + timestamp), registers it with the `ConnectionManager`, and enqueues
   the request to its assigned receiver, which publishes it to
   the `agent_request_queue` channel. The HTTP call immediately returns a
   `StreamingResponse` that consumes the connection's response queue.
3. **Pick-up** — a worker process receives the event and acquires the per-connection
   Redis lock (guaranteeing single handling).
4. **Agent run** — `agent_implementation` builds the coordinator agent:
   - MySQL checkpointer keyed by `thread_id` (conversation continuity across requests),
   - Postgres store for cross-thread/episodic memory,
   - `user_id` pinned into the runnable context so tools operate on the right customer.
   LLM calls flow through the LiteLLM gateway (input guardrail → model w/ fallback →
   output guardrail); RAG hits Chroma; business tools hit MySQL.
5. **Human-in-the-loop** — if the previous turn interrupted on `refund`, the user's
   reply is scanned for approval wording (`check_approval_wording`); if found the agent
   is resumed with `Command(resume={"decisions": [...]})`, otherwise the text is sent
   as a normal new message. New refund requests raise an interrupt surfaced to the
   customer as an assistant message asking them to agree/reject.
6. **Stream back** — LangGraph `astream_events(v2)` is translated to AG-UI events
   (subagent model calls are filtered out; only root-agent text streams to the UI;
   render tools become `ToolCall*` events). Each event is wrapped in a `Response`,
   published to `agent_response_queue`, routed by the owning distributor into the
   connection queue, SSE-encoded by the AG-UI `EventEncoder`, and rendered by the
   React client (text deltas + product/membership/purchase/refund cards).
7. **Teardown** — on completion or client disconnect, the generator's `finally` block
   disconnects the connection and removes all queue/mapping state. Traces for the run
   land in Langfuse; spans flow via OTel collector to Zipkin.

---

## 6. Guardrails & Safety

Mounted inside the LiteLLM gateway (so they apply to **every** model call):

- **`customer-service-input-guard` (pre_call)** — masks PII (emails, phones, card
  numbers, ...) in prompts; rejects detected prompt-injection attempts with HTTP 400.
- **`customer-service-output-guard` (post_call)** — masks PII/echoed secrets in
  completions; blocks configured banned terms.

Toggles via env: `GUARDRAIL_MASK_PII`, `GUARDRAIL_BLOCK_PROMPT_INJECTION`,
`GUARDRAIL_BLOCKED_TERMS`. Plus application-level controls: human approval required
before any refund executes, per-connection Redis locks, idempotency keys, and
circuit breakers (`pybreaker`/`aiobreaker`) around external calls.

## 7. Observability

- **Langfuse** (web on `:3000`) — LLM traces via the callback handler attached to every
  agent run (`run_name=sql_agent_server_<worker>`); backed by ClickHouse + MinIO.
- **OpenTelemetry** — services (incl. Chroma) export to `otel-collector`, which forwards
  to **Zipkin** (`:9411`).

---

## 8. Running the Stack

```bash
# 0. Requirements: Docker Desktop VM with >= 12 GiB memory
#    (vLLM reserves ~30% of VM RAM for the embedding model cache).

# 1. Create .env in the repo root (docker-compose loads it) with at least:
#    ZAI_API_KEY, VLLM_API_KEY, LITELLM_MASTER_KEY, REDIS_AUTH,
#    REDIS_SECRET_KEY, POSTGRES_DATABASE_URL, LITELLM_API_KEY

# 2. Start everything (infra + agent-server + frontend)
docker compose up -d --build

# 3. Ingest the knowledge base into Chroma + seed demo business data
python scripts/ingest_knowledge_base.py
python scripts/seed_demo_data.py --yes
```

- Frontend: http://localhost:5173
- Agent API: http://localhost:8000 (`/actuator/health` for liveness)
- Langfuse UI: http://localhost:3000 · Zipkin: http://localhost:9411 ·
  LiteLLM gateway: http://localhost:4000

Useful scripts: `scripts/smoke_test_auth.py` (auth flow check),
`scripts/test_agui_pipeline.py` (mock-mode AG-UI pipeline test, no LLM/Redis/DB needed).

### Key environment variables

| Variable | Purpose |
|---|---|
| `ZAI_API_KEY` / `VLLM_API_KEY` | Upstream model credentials (gateway) |
| `LITELLM_API_KEY` / `LITELLM_API_BASE` | Gateway credentials/endpoint (agent) |
| `LITELLM_MASTER_KEY` | Gateway master key |
| `LLM_PRIMARY_MODEL` / `LLM_MODEL_LIST` | Chat model selection + fallback chain |
| `REDIS_AUTH` / `REDIS_SECRET_KEY` / `REDIS_CLUSTER_MODE` | Redis password, idempotency JWT secret, cluster toggle |
| `POSTGRES_DATABASE_URL` | Postgres store (shared instance) |
| `NUMBER_REQUEST_RECEIVER` / `NUMBER_RESPONSE_DISTRIBUTOR` / `NUMBER_REQUEST_WORKER` | Event-bus stage fan-out (default 8 each) |
| `EVENT_BUS_REQUEST_QUEUE` / `EVENT_BUS_RESPONSE_QUEUE` | Pub/sub channel names |
| `GUARDRAIL_MASK_PII` / `GUARDRAIL_BLOCK_PROMPT_INJECTION` / `GUARDRAIL_BLOCKED_TERMS` | Guardrail toggles |
