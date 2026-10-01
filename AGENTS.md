# AGENTS.md — Aurus IT Helpdesk

Aurus IT Helpdesk is an internal IT service management platform for Aurus Financial Group. It handles the full ticket lifecycle with priority-based SLA enforcement and a real-time service desk dashboard.

## Commands

- **Install dependencies**: `pip install -r requirements.txt`
- **Run the development server**: `uvicorn main:app --reload` (interactive docs at `/docs`)
- **Run the tests**: `pytest` (run from the project root; uses FastAPI's `TestClient`)

## Project layout

- `main.py` — FastAPI app and all route handlers. Translates store results into HTTP responses; raises 404s when a ticket ID is not found.
- `models.py` — Pydantic contracts: `Ticket` (resource shape, used as `response_model`), `CreateTicketRequest`, `UpdateTicketRequest`. Status and priority are constrained with `Literal` types.
- `store.py` — `TicketStore`, the in-memory data layer. Owns ID generation, SLA deadline math (`_SLA_HOURS`), startup ticket initialization, status filtering, and newest-first sorting.
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
- **Storage**: in-memory for the v1 POC. Database persistence is planned for v2.
