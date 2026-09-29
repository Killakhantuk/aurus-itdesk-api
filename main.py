from fastapi import FastAPI, HTTPException
from typing import Optional

from models import Ticket, CreateTicketRequest, UpdateTicketRequest
from store import TicketStore

app = FastAPI(title="Aurus IT Helpdesk API", version="1.0.0")
store = TicketStore()


@app.post("/tickets", response_model=Ticket, status_code=201)
def create_ticket(req: CreateTicketRequest):
    return store.create(req)


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