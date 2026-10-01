from typing import Optional
from datetime import datetime, timedelta, timezone
import uuid

from models import Ticket, CreateTicketRequest, UpdateTicketRequest

_SLA_HOURS = {"low": 72, "medium": 24, "high": 8, "critical": 4}

_INITIAL_TICKETS = [
    (
        "VPN access not working for new hire",
        "New employee cannot connect to corporate VPN after onboarding. Affects productivity from day one.",
        "high",
        "eng-support@aurus.com",
    ),
    (
        "Laptop battery draining unusually fast",
        "MacBook Pro 2023 losing 30% charge per hour under light usage. Suspected background process issue.",
        "low",
        None,
    ),
    (
        "Outlook mobile sync stopped after MDM update",
        "Email no longer syncing on mobile devices following last week's MDM policy push.",
        "medium",
        "helpdesk@aurus.com",
    ),
    (
        "Critical: Authentication service down — all users locked out",
        "SSO provider returning 503. No engineers can access internal tools. Escalation required immediately.",
        "critical",
        None,
    ),
]


class TicketStore:
    def __init__(self):
        self._tickets: dict[str, Ticket] = {}
        self._load_initial_tickets()

    def _load_initial_tickets(self):
        for title, desc, priority, assignee in _INITIAL_TICKETS:
            ticket = self.create(CreateTicketRequest(
                title=title,
                description=desc,
                priority=priority,
                assignee=assignee,
            ))
            if title == "Critical: Authentication service down — all users locked out":
                self._tickets[ticket.id] = ticket.model_copy(update={
                    "sla_deadline": datetime.now(timezone.utc) - timedelta(hours=2),
                })

    def create(self, req: CreateTicketRequest) -> Ticket:
        now = datetime.utcnow()
        ticket = Ticket(
            id=str(uuid.uuid4())[:8],
            title=req.title,
            description=req.description,
            status="open",
            priority=req.priority,
            assignee=req.assignee,
            created_at=now,
            updated_at=now,
            sla_deadline=now + timedelta(hours=_SLA_HOURS[req.priority]),
        )
        self._tickets[ticket.id] = ticket
        return ticket

    def get(self, ticket_id: str) -> Optional[Ticket]:
        return self._tickets.get(ticket_id)

    def list(self, status_filter: Optional[str] = None) -> list[Ticket]:
        tickets = list(self._tickets.values())
        if status_filter:
            tickets = [t for t in tickets if t.status == status_filter]
        return sorted(tickets, key=lambda t: t.created_at, reverse=True)

    def escalate_overdue(self) -> list[Ticket]:
        """Escalate critical, open, unassigned tickets whose SLA deadline has passed."""
        now = datetime.now(timezone.utc)
        escalated: list[Ticket] = []
        for ticket_id, ticket in self._tickets.items():
            if ticket.priority != "critical" or ticket.status != "open":
                continue
            if ticket.assignee and ticket.assignee.strip():
                continue
            if not self._is_past_deadline(ticket.sla_deadline, now):
                continue
            updated = ticket.model_copy(update={
                "status": "escalated",
                "updated_at": now,
            })
            self._tickets[ticket_id] = updated
            escalated.append(updated)
        return sorted(escalated, key=lambda t: t.created_at, reverse=True)

    @staticmethod
    def _is_past_deadline(deadline: Optional[datetime], now: datetime) -> bool:
        if deadline is None:
            return False
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return deadline < now

    def update(self, ticket_id: str, req: UpdateTicketRequest) -> Optional[Ticket]:
        ticket = self._tickets.get(ticket_id)
        if not ticket:
            return None
        updated = ticket.model_copy(update={
            "status": req.status if req.status is not None else ticket.status,
            "assignee": req.assignee if req.assignee is not None else ticket.assignee,
            "priority": req.priority if req.priority is not None else ticket.priority,
            "updated_at": datetime.utcnow(),
        })
        self._tickets[ticket_id] = updated
        return updated

    def delete(self, ticket_id: str) -> bool:
        if ticket_id not in self._tickets:
            return False
        del self._tickets[ticket_id]
        return True
