from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


class Ticket(BaseModel):
    id: str
    title: str
    description: str
    status: Literal["open", "in_progress", "resolved", "closed", "escalated"]
    priority: Literal["low", "medium", "high", "critical"]
    assignee: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    sla_deadline: Optional[datetime] = None


class CreateTicketRequest(BaseModel):
    title: str
    description: str
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    assignee: Optional[str] = None


class UpdateTicketRequest(BaseModel):
    status: Optional[Literal["open", "in_progress", "resolved", "closed", "escalated"]] = None
    assignee: Optional[str] = None
    priority: Optional[Literal["low", "medium", "high", "critical"]] = None