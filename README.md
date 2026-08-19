# YouTube Cook Backend

Backend service for **YouTube Cook**, an application that transforms cooking videos into structured, usable recipe data using Google Gemini.

The service accepts a YouTube video, analyzes its cooking content with Gemini, and returns structured information such as ingredients, cooking steps, temperatures, timings, and useful tips.

The backend is built with **FastAPI**, uses **WebSocket communication** for video analysis, **Redis** for lightweight quota control, and **PostgreSQL** for operational analytics such as AI request history, token usage, cost, latency, and error tracking.

---

## Overview

YouTube cooking videos contain useful information, but recipes are often scattered across narration, subtitles, and visual context.

YouTube Cook turns that unstructured video content into structured recipe data that can be consumed directly by a mobile application.

At a high level:

```text
YouTube Video
      │
      ▼
React Native Client
      │
      │ WebSocket
      ▼
FastAPI Backend
      │
      ├── Quota Validation ───────► Redis
      │
      ├── Video Analysis ─────────► Gemini API
      │
      └── Request Analytics ──────► PostgreSQL
                                      │
                                      ▼
                               Admin Dashboard
```

The backend intentionally remains relatively lightweight. Long-running background job infrastructure such as Kafka or Celery is currently avoided because video analysis requests are user-driven and the client can explicitly retry failed requests when appropriate.

---

## Features

- YouTube cooking video analysis with Google Gemini
- Structured recipe extraction
- WebSocket-based analysis endpoint
- Per-client usage quota management with Redis
- Global usage limits for controlled testing
- Gemini request and retry tracking
- Token usage monitoring
- Estimated Gemini API cost tracking
- Request latency monitoring
- Error classification and HTTP status tracking
- PostgreSQL-based operational analytics
- Lightweight admin dashboard
- Health-check endpoints for application and database status
- Async PostgreSQL access with SQLAlchemy

---

## Tech Stack

### Backend

- Python 3.11
- FastAPI
- Uvicorn
- SQLAlchemy Async
- asyncpg
- Pydantic

### AI

- Google Gemini API
- `google-genai`

### Data

- PostgreSQL / Neon
- Redis / Upstash Redis

### Deployment

- Render

### Client

The backend is designed primarily for a React Native mobile application.

---

## Project Structure

```text
.
├── README.md
├── main.py
├── pyproject.toml
├── uv.lock
│
├── app
│   ├── main.py
│   ├── enums.py
│   │
│   ├── api
│   │   └── routes.py
│   │
│   ├── core
│   │   ├── config.py
│   │   ├── redis.py
│   │   └── security.py
│   │
│   ├── db
│   │   ├── base.py
│   │   └── session.py
│   │
│   ├── dtos
│   │   ├── gemini.py
│   │   └── quota.py
│   │
│   ├── models
│   │   ├── gemini_request.py
│   │   └── video_analysis.py
│   │
│   ├── pricing
│   │   └── gemini.py
│   │
│   ├── routes
│   │   ├── dashboard.py
│   │   ├── health.py
│   │   └── video.py
│   │
│   ├── schemas
│   │   ├── dashboard.py
│   │   ├── schemas.py
│   │   └── video.py
│   │
│   └── services
│       ├── dashboard.py
│       ├── gemini.py
│       ├── pricing.py
│       └── quota.py
│
└── tools
    └── dashboard
        └── index.html
```

### Responsibilities

| Directory | Responsibility |
|---|---|
| `core/` | Application configuration, Redis connection, security-related utilities |
| `db/` | SQLAlchemy base and async database session |
| `models/` | PostgreSQL ORM models |
| `dtos/` | Internal data-transfer objects |
| `schemas/` | API request/response schemas |
| `routes/` | HTTP and WebSocket endpoints |
| `services/` | Business logic |
| `pricing/` | Gemini pricing definitions/calculation |
| `tools/dashboard/` | Lightweight administrative dashboard |

This separation keeps transport logic, business logic, persistence, and external AI integration from becoming tightly coupled.

---

## Video Analysis Flow

A video analysis request follows approximately this lifecycle:

```text
Client
  │
  │ 1. Connect
  ▼
WebSocket Endpoint
  │
  │ 2. Validate request / quota
  ▼
Quota Service ───────────► Redis
  │
  │ 3. Start analysis
  ▼
Gemini Service
  │
  │ 4. Send YouTube video
  ▼
Google Gemini
  │
  │ 5. Structured result
  ▼
FastAPI Backend
  │
  ├── Return result to client
  │
  └── Record analytics
          │
          ▼
      PostgreSQL
```

The backend is responsible for processing an individual request and reporting its result.

Automatic long-lived background retry processing is intentionally not a requirement of the current architecture. When a transient upstream failure occurs, the backend returns an appropriate failure state so that retry policy can be handled by the mobile client.

---

## Gemini Analysis

Gemini is used to interpret cooking content directly from the supplied YouTube video.

The extracted recipe data is designed to contain information such as:

- Recipe title
- Ingredients
- Ingredient quantities when available
- Cooking steps
- Cooking temperatures
- Cooking durations
- Additional cooking tips

The analysis layer is isolated under:

```text
app/services/gemini.py
```

This keeps Gemini-specific API logic separate from the WebSocket route and makes it easier to replace or extend the model integration later.

---

## Request Tracking

The service stores operational information separately from the generated recipe itself.

Two primary database entities are used.

### `video_analyses`

Represents one logical video-analysis operation.

Important fields include:

```text
id
youtube_video_id
youtube_url
title
thumbnail_url
video_duration_seconds
status
processing_duration_ms
created_at
processed_at
```

Supported analysis states include:

```text
queued
processing
retry_wait
completed
failed
```

This table tracks the lifecycle of the **overall video analysis**, rather than individual Gemini calls.

---

### `gemini_requests`

Represents an individual Gemini request attempt belonging to a video analysis.

Important fields include:

```text
id
analysis_id
attempt_number
model_name
status

input_tokens
output_tokens
thoughts_tokens
cached_tokens
total_tokens

cost_usd
duration_ms

http_status
error_type
error_message

created_at
completed_at
```

A single video analysis may therefore contain multiple Gemini request records:

```text
VideoAnalysis
    │
    ├── GeminiRequest #1
    ├── GeminiRequest #2
    └── GeminiRequest #3
```

The `(analysis_id, attempt_number)` pair is unique.

This model allows retries to be tracked without overwriting the history of previous attempts.

---

## Why Analysis and Gemini Requests Are Separate

An analysis and an API request represent different concepts.

For example:

```text
Analysis #123
│
├── Attempt #1 → 503 Service Unavailable
│
└── Attempt #2 → Completed
```

From the application's perspective, the analysis eventually succeeded.

From an operational perspective, however, two Gemini requests occurred.

Keeping both concepts separate makes it possible to calculate:

- Gemini failure rate
- Retry frequency
- Average attempts per analysis
- Token usage
- API cost
- Upstream error distribution
- Processing latency
- Successful-analysis rate

without losing individual request history.

---

## Error Handling

External AI APIs can occasionally return transient failures.

Gemini request records support storing:

```text
http_status
error_type
error_message
```

This allows the backend to distinguish application-level analysis status from the actual upstream API failure.

Typical operational categories can include:

```text
rate_limit
service_unavailable
timeout
invalid_request
upstream_error
internal_error
```

The exact error classification is handled by the backend rather than relying only on raw exception messages.

For temporary upstream failures, the current application architecture favors returning a clear error to the client rather than maintaining an indefinite backend job.

This keeps the server stateless enough for the current scale and allows the mobile application to decide whether and when to retry.

---

## Quota Management

Redis is used for lightweight request quota management.

The current testing environment is designed around a small group of authorized testers with both:

- per-client daily limits
- global daily limits

Redis is a good fit for this information because quota counters are:

- frequently accessed
- short-lived
- inexpensive to recreate
- naturally compatible with TTL-based expiration

Persistent analytics are stored separately in PostgreSQL.

Conceptually:

```text
Redis
├── client quota
├── global quota
└── expiration / reset state

PostgreSQL
├── video analysis history
├── Gemini request history
├── token usage
├── API cost
└── errors / latency
```

This prevents temporary counter state from being mixed with long-lived operational data.

---

## Database

PostgreSQL is accessed asynchronously through SQLAlchemy.

The application uses an async engine and session factory:

```python
engine = create_async_engine(
    settings.database_url,
    connect_args={
        "ssl": "require",
    },
    pool_pre_ping=True,
)
```

The project currently targets Neon-hosted PostgreSQL.

### Neon and `asyncpg`

When using Neon with `asyncpg`, SSL parameters embedded in a PostgreSQL URL may not always map directly to `asyncpg` connection arguments.

The application therefore provides SSL configuration through SQLAlchemy's `connect_args`.

When configuring `DATABASE_URL`, make sure its format matches the connection strategy used by `app/db/session.py`.

---

## Administrative Analytics

The project includes a lightweight administrative dashboard under:

```text
tools/dashboard/index.html
```

Dashboard-related routes and business logic are separated into:

```text
app/routes/dashboard.py
app/services/dashboard.py
app/schemas/dashboard.py
```

The dashboard can use the stored request data to provide operational metrics such as:

- number of analyses
- success / failure counts
- total Gemini requests
- retry counts
- token consumption
- estimated API cost
- average processing duration
- error distribution

The dashboard is intended for service monitoring rather than end-user recipe storage.

---

## Health Checks

Health endpoints are located under:

```text
app/routes/health.py
```

Health checks can be used to verify both application availability and external dependencies such as PostgreSQL.

A typical database health response may resemble:

```json
{
  "status": "ok",
  "database": "connected"
}
```

or:

```json
{
  "status": "error",
  "database": "disconnected",
  "error": "..."
}
```

These endpoints are useful both during local development and when diagnosing deployment issues on Render.

---

## Local Development

### Requirements

- Python 3.11
- `uv`
- PostgreSQL
- Redis
- Google Gemini API credentials

Clone the repository:

```bash
git clone <repository-url>
cd youtube-cook-backend
```

Install dependencies:

```bash
uv sync
```

---

## Environment Variables

Create a `.env` file in the project root.

At minimum, the application requires configuration for:

```env
DATABASE_URL=
REDIS_URL=
GEMINI_API_KEY=
```

Additional configuration may be defined in:

```text
app/core/config.py
```

Do not commit `.env` files or API credentials to Git.

---

## Running the Server

Start the FastAPI application locally with:

```bash
uv run uvicorn app.main:app --reload
```

Depending on the root entrypoint used by the project, the top-level `main.py` may also be used.

The local development server will normally be available at:

```text
http://localhost:8000
```

FastAPI documentation is available at:

```text
http://localhost:8000/docs
```

for HTTP endpoints.

WebSocket endpoints are not represented as fully interactive endpoints in Swagger UI and should be tested separately.

---

## Testing WebSocket Connections

A command-line WebSocket client such as `websocat` can be useful during development.

Example:

```bash
websocat ws://localhost:8000/api/v1/ws/analyze-video
```

For production deployments:

```bash
websocat wss://<host>/api/v1/ws/analyze-video
```

Use `wss://` when connecting through HTTPS.

A normal `ws://` request to an HTTPS deployment may be redirected before the WebSocket upgrade occurs.

---

## Deployment

The backend is currently designed to run on Render.

Production infrastructure currently consists conceptually of:

```text
Render
  │
  └── FastAPI Backend
       │
       ├── Google Gemini API
       ├── Upstash Redis
       └── Neon PostgreSQL
```

Environment variables should be configured through the deployment platform rather than committed to the repository.

After deployment, verify:

1. Application health endpoint
2. Database connectivity
3. Redis connectivity
4. WebSocket upgrade over `wss://`
5. Gemini request execution
6. Request analytics persistence

---

## Design Decisions

### Why WebSocket?

Video analysis can take substantially longer than a normal CRUD request.

WebSocket communication allows the backend to keep a request channel open and makes it possible to introduce intermediate progress events later without redesigning the API.

---

### Why Redis?

Quota information is temporary and frequently updated.

Redis provides fast atomic counters and TTL expiration without creating unnecessary writes to the primary relational database.

---

### Why PostgreSQL?

Operational analytics are relational and long-lived.

The service needs to answer questions such as:

```text
Which analysis generated this Gemini request?
How many attempts did this analysis require?
Which errors occur most often?
How much did Gemini requests cost today?
How many tokens were consumed?
```

These relationships and aggregations fit naturally in PostgreSQL.

---

### Why Not Store Everything in PostgreSQL?

Not every piece of application state has the same persistence requirements.

Short-lived counters belong in Redis, while durable request history belongs in PostgreSQL.

Recipe storage is intentionally treated as a separate product concern rather than being coupled directly to analytics persistence.

---

### Why No Message Queue Yet?

A queue-based architecture using systems such as Kafka or Celery could provide durable background processing and automatic retries.

For the current application, that complexity is not justified.

The workload is relatively small, requests originate interactively from the mobile application, and immediate completion is not a strict product requirement.

The simpler architecture provides:

- fewer infrastructure dependencies
- easier deployment
- easier debugging
- explicit client-side retry behavior
- lower operational overhead

A durable job queue can be introduced later if workload or reliability requirements change.

---

## Future Improvements

Possible future work includes:

- richer progress events over WebSocket
- persistent recipe storage
- object storage for generated artifacts
- recipe search and history
- multi-language recipe output
- RAG over previously analyzed recipes
- PostgreSQL vector search
- user authentication
- improved admin dashboard
- automatic anomaly monitoring
- database migrations with Alembic
- integration and load testing
- structured application logging
- tracing and observability
- durable background processing if scale requires it

The project deliberately avoids introducing these components before they are required.

---

## Development Philosophy

The backend follows a simple principle:

> Use persistent infrastructure for persistent problems, and temporary infrastructure for temporary state.

This currently means:

```text
Gemini       → video understanding
FastAPI      → API orchestration
WebSocket    → long-running client communication
Redis        → temporary quota state
PostgreSQL   → durable analytics
Render       → application hosting
```

The architecture is intentionally small enough to operate easily while keeping clear extension points for future growth.

---
## Getting Started
Clone the repository:
```bash
git clone https://github.com/Jongeum-k/YoutubeCookBackEnd.git
cd VivEngineProject
```

Install dependencies:
```bash
uv sync
```

Set up environment variables and Docker config:
```bash
# Create .env and docker-compose.yml from the provided examples
cp .env.example .env
```
Open `.env` and fill in your credentials (GEMINI API KEY, `DATABASE_URL`, `REDIS_URL`, etc.).

Start the development environment:
```bash
uv run uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload
```
---
## License

This project is currently intended for private development and testing.

Add an explicit license before distributing or open-sourcing the project.