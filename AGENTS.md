# AGENTS.md — Aurus IT Helpdesk API

FastAPI service for managing IT support tickets (create, list, filter, update, delete) with priority-based SLA deadlines. Storage is in-memory only.

## Commands

- **Install dependencies**: `pip install -r requirements.txt`
- **Run the development server**: `uvicorn main:app --reload` (interactive docs at `/docs`)
- **Run the tests**: `pytest` (run from the project root; uses FastAPI's `TestClient`)

## Project layout

- `main.py` — FastAPI app and all route handlers. Translates store results into HTTP responses; raises 404s when a ticket ID is not found.
- `models.py` — Pydantic contracts: `Ticket` (resource shape, used as `response_model`), `CreateTicketRequest`, `UpdateTicketRequest`. Status and priority are constrained with `Literal` types.
- `store.py` — `TicketStore`, the in-memory data layer. Owns ID generation, SLA deadline math (`_SLA_HOURS`), seed data, status filtering, and newest-first sorting.
- `tests/test_tickets.py` — Integration tests through the real ASGI app, one per endpoint plus 404 and filter cases.
- `requirements.txt` — `fastapi`, `uvicorn[standard]`, `pydantic`, `httpx` (needed by `TestClient`), `pytest`.

## Coding conventions

### Layering

Three layers, with strict dependencies flowing downward:

1. **Routes** (`main.py`) — HTTP concerns only: parse input, call the store, map results to status codes. Handlers never touch the ticket dict directly.
2. **Models** (`models.py`) — the contract between routes and store. Request bodies in, `Ticket` out.
3. **Store** (`store.py`) — all data logic: ID generation, SLA computation, filtering, sorting. The store never knows about HTTP.

### Pydantic v2 idioms

- Use `Literal` types for enum-like fields (status, priority), not Python `Enum`s.
- Use `model_copy(update={...})` for updates rather than mutating models in place.
- Optional fields are declared `Optional[X] = None`.

### PATCH semantics

Partial updates use "ignore if `None`": a `None` field in `UpdateTicketRequest` means "leave unchanged". Implement this in the store layer, keeping request models purely declarative.

### Error responses

Error details must follow RFC 7807 shape with `type`/`title`/`status` fields:

```python
raise HTTPException(
    status_code=404,
    detail={"type": "about:blank", "title": "Ticket not found", "status": 404},
)
```

### Datetimes

Use `datetime.now(timezone.utc)` for new code. Do not use `datetime.utcnow()` — it is deprecated (Python 3.12+) and produces naive datetimes.

## Rules

- **Never log PII** — no user emails, employee IDs, or personal data in logs.
- **All new endpoints must include a `response_model`.**
- **Tests are required before any task is considered complete.**
- **Do not introduce a database dependency** — keep storage in-memory for now.

## Known gaps (do not fix unless explicitly asked)

These correctness issues exist in the current code. Leave them alone unless the task explicitly asks for them:

1. **SLA deadlines are not recomputed on priority change** (`store.py`, `update`): escalating a ticket to `critical` keeps the deadline computed for its original priority.
2. **ID collision risk** (`store.py`, `create`): `str(uuid.uuid4())[:8]` is only ~32 bits of ID; collisions become likely around ~65k tickets and a create would silently overwrite an existing ticket.
3. **`assignee` cannot be cleared**: because `None` means "no change" in PATCH semantics, there is no way to unassign a ticket.
4. **`datetime.utcnow()` in existing code**: `store.py` predates the timezone-aware convention above; existing call sites are naive datetimes.
5. **Unvalidated `status` query param** (`main.py`, `list_tickets`): `GET /tickets?status=anything` returns `200 []` instead of a 422 because the param is a plain `Optional[str]`.
6. **No thread safety**: sync handlers run in a threadpool against a shared dict with no locking; concurrent requests can race on read-modify-write operations.
7. **No field constraints**: `title` and `description` accept empty strings (no `min_length`, no length caps).
8. **Shared test state**: tests run against one module-level store with no fixture isolation; they depend on seed data and each other's leftovers.
