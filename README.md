# Aurus IT Helpdesk

Aurus IT Helpdesk is an internal IT service management platform for Aurus Financial Group. It manages the full ticket lifecycle with priority-based SLA enforcement and a real-time service desk dashboard.

## What it does

- **Ticket management** — Create, list, filter, retrieve, update, and delete IT support tickets.
- **SLA enforcement** — Assign response targets based on ticket priority: low, medium, high, or critical.
- **Escalation** — Automatically escalate critical, overdue tickets that do not have an assigned owner.
- **Service desk dashboard** — Monitor queue health, search tickets, update status and assignees, review ticket details, and initiate SLA enforcement from a browser.

## Tech stack

- Python
- FastAPI
- Pydantic v2
- Vanilla JavaScript, HTML, and CSS
- In-memory storage for the v1 POC, with database persistence planned for v2

## Quick start

```bash
pip install -r requirements.txt
uvicorn main:app --reload
pytest
```

Open `http://127.0.0.1:8000/` for the service desk dashboard and `http://127.0.0.1:8000/docs` for the interactive API documentation.

## API overview

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/tickets` | Create a ticket |
| `GET` | `/tickets` | List tickets, optionally filtered by status |
| `GET` | `/tickets/{ticket_id}` | Retrieve a ticket |
| `PATCH` | `/tickets/{ticket_id}` | Partially update a ticket |
| `POST` | `/tickets/escalate` | Escalate eligible overdue tickets |
| `DELETE` | `/tickets/{ticket_id}` | Delete a ticket |

All ticket responses use the Pydantic `Ticket` contract. Invalid request fields return FastAPI validation responses, and missing ticket IDs return RFC 7807-compatible error details.

## Architecture

The service uses three layers with dependencies flowing downward. Route handlers in `main.py` own HTTP concerns and translate store results into responses. Pydantic contracts in `models.py` define the request and response shapes. `TicketStore` in `store.py` owns ticket data, ID generation, SLA calculation, filtering, sorting, startup initialization, updates, deletion, and escalation logic.

## Aurus Financial Group context

Aurus IT Helpdesk supports internal technology operations for Aurus Financial Group. The service desk dashboard gives IT teams a shared view of operational tickets, ownership, priority, status, and SLA deadlines. The codebase is structured as an enterprise proof of concept, with the v1 storage boundary kept in memory while the v2 persistence layer is planned.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `main.py` | FastAPI application, route handlers, dashboard serving |
| `models.py` | Pydantic v2 request and response contracts |
| `store.py` | Ticket data access and SLA enforcement |
| `static/index.html` | Service desk dashboard |
| `tests/` | API and dashboard integration tests |
