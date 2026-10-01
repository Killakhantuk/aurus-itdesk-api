from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from models import Ticket, CreateTicketRequest, UpdateTicketRequest
from store import TicketStore

DASHBOARD_PATH = Path(__file__).resolve().parent / "static" / "index.html"

app = FastAPI(title="Aurus IT Helpdesk API", version="1.0.0")
store = TicketStore()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(DASHBOARD_PATH, media_type="text/html")


@app.post("/tickets", response_model=Ticket, status_code=201)
def create_ticket(req: CreateTicketRequest):
    return store.create(req)


@app.post("/tickets/escalate", response_model=list[Ticket])
def escalate_tickets():
    return store.escalate_overdue_critical()


@app.get("/tickets", response_model=list[Ticket])
def list_tickets(status: Optional[str] = None):
    return store.list(status_filter=status)


@app.get("/tickets/{ticket_id}", response_model=Ticket)
def get_ticket(ticket_id: str):
    ticket = store.get(ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=404,
            detail={"type": "about:blank", "title": "Ticket not found", "status": 404},
        )
    return ticket


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
def update_ticket(ticket_id: str, req: UpdateTicketRequest):
    ticket = store.update(ticket_id, req)
    if not ticket:
        raise HTTPException(
            status_code=404,
            detail={"type": "about:blank", "title": "Ticket not found", "status": 404},
        )
    return ticket


@app.delete("/tickets/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: str):
    if not store.delete(ticket_id):
        raise HTTPException(
            status_code=404,
            detail={"type": "about:blank", "title": "Ticket not found", "status": 404},
        )